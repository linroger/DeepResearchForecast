"""deerflow_bridge/deerflow_research.py 纯 helper 的离线单测（PM-1 / INT-2 / RQ-6）。

桥脚本运行在 DeerFlow 自己的 venv 里、模块级只 import 标准库（``deerflow`` 相关 import
都在函数体内），因此可从 backend 测试里直接 import 做纯函数测试——只需把 deerflow_bridge
目录挂到 sys.path（backend conftest 只挂了 backend/，不含桥目录）。全部纯函数、零网络、零 LLM。
"""

import hashlib
import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BRIDGE_DIR = os.path.join(_REPO_ROOT, "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import deerflow_research as d  # noqa: E402


def test_agentic_delegation_prompt_uses_actual_lane_cap(monkeypatch):
    monkeypatch.setenv("RESEARCH_AGENTIC_SEARCH", "true")
    monkeypatch.setenv("DEER_FLOW_MAX_CONCURRENT_SUBAGENTS", "2")
    d._set_agentic_delegation(True)
    try:
        prompt = d._agentic_delegation_block(False)
        assert "at most 2 parallel tasks" in prompt
        assert "3–5" not in prompt and "3-5" not in prompt
        assert d._stream_model_lease_weight() == 1
    finally:
        d._set_agentic_delegation(False)


# ---------------------------------------------------------------- PM-1 tokenizer / phrases

def test_salient_phrases_keeps_four_digit_years():
    """4 位年份必须作为独立 token 保留（旧的 `[A-Za-z]…` 起始类会整个吃掉 '2026'）。"""
    phrases = d._pm_salient_phrases("Who will win the 2026 US House control election?")
    joined = " ".join(phrases)
    assert "2026" in joined
    # 年份不应被丢弃或与前词错误吞并成无年份短语
    assert any(p.strip().startswith("2026") or " 2026" in p for p in phrases)


def test_salient_phrases_blacklists_generic_words():
    """泛化名词（key/factors/outcome/analysis/impact）作为停用词断句，不进入短语。"""
    phrases = d._pm_salient_phrases("Key factors and outcome analysis for 2028 impact")
    joined = " ".join(phrases).lower()
    for bad in ("key", "factors", "outcome", "analysis", "impact"):
        assert bad not in joined.split()
    assert "2028" in joined  # 年份仍保留


def test_salient_phrases_clause_boundary_truncation():
    """子句边界（逗号）强制断句：'House control, Senate races' 不得合成跨子句短语。"""
    phrases = d._pm_salient_phrases("House control, Senate races")
    # 不允许出现同时含 control 和 Senate 的单一短语（说明跨了逗号）
    assert not any("control" in p.lower() and "senate" in p.lower() for p in phrases)


# ---------------------------------------------------------------- PM-1 query derivation

def test_derive_queries_cap_is_twelve():
    q = d._pm_derive_queries(
        "A very long forecasting question about many distinct topics and races",
        hot_topics=[f"topic{i}" for i in range(20)],
        actor_names=[f"actor{i}" for i in range(20)],
    )
    assert len(q) <= 12


def test_derive_queries_reserves_actor_slots():
    """问题短语+热点即使能占满 12 名额，也必须为 ≥2 个 actor 名留位。"""
    q = d._pm_derive_queries(
        "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi",
        hot_topics=[f"hot{i}" for i in range(20)],
        actor_names=["Mike Johnson", "Hakeem Jeffries", "Chuck Schumer"],
    )
    assert "Mike Johnson" in q
    assert "Hakeem Jeffries" in q
    assert len(q) <= 12


def test_derive_queries_no_actors_is_fine():
    q = d._pm_derive_queries("2026 US House control", hot_topics=None, actor_names=None)
    assert q and all(isinstance(x, str) for x in q)


# ---------------------------------------------------------------- PM-1 LLM query parsing

def test_parse_market_queries_json_array():
    out = d._parse_market_queries('["House control 2026", "Ohio Senate winner"]')
    assert out == ["House control 2026", "Ohio Senate winner"]


def test_parse_market_queries_line_fallback():
    out = d._parse_market_queries("1. House control 2026\n2) Ohio Senate winner\n- Fed rate cut")
    assert out == ["House control 2026", "Ohio Senate winner", "Fed rate cut"]


def test_parse_market_queries_embedded_json_and_dedup():
    out = d._parse_market_queries('Here you go: ["A market", "A market", "B market"] done')
    assert out == ["A market", "B market"]


def test_parse_market_queries_empty_returns_empty():
    assert d._parse_market_queries("") == []
    assert d._parse_market_queries("   ") == []


def test_parse_market_queries_truncates_long():
    out = d._parse_market_queries('["one two three four five six seven eight"]', max_words=6)
    assert out == ["one two three four five six"]


# ---------------------------------------------------------------- PM-1 relevance gate

def test_parse_relevance_scores_dict():
    got = d._parse_relevance_scores('{"111": 8, "222": 3, "999": 5}', ["111", "222"])
    assert got == {"111": 8.0, "222": 3.0}  # 999 未知 id 被过滤


def test_parse_relevance_scores_list_shape():
    got = d._parse_relevance_scores('[{"id":"111","score":7},{"market_id":"222","relevance":2}]',
                                    ["111", "222"])
    assert got == {"111": 7.0, "222": 2.0}


def test_parse_relevance_scores_unparseable_returns_empty():
    assert d._parse_relevance_scores("not json at all", ["1"]) == {}
    assert d._parse_relevance_scores("", ["1"]) == {}


def test_apply_relevance_gate_drops_and_ranks():
    markets = [
        {"market_id": "low", "volume": 999.0},
        {"market_id": "hi", "volume": 10.0},
        {"market_id": "mid", "volume": 50.0},
    ]
    scores = {"low": 2.0, "hi": 9.0, "mid": 6.0}
    kept = d._apply_relevance_gate(markets, scores, 5.0)
    ids = [m["market_id"] for m in kept]
    assert ids == ["hi", "mid"]  # low(2)<5 丢弃；按 relevance 降序
    assert all("relevance_score" in m for m in kept)


def test_apply_relevance_gate_empty_scores_keeps_all_by_volume():
    markets = [{"market_id": "a", "volume": 5.0}, {"market_id": "b", "volume": 50.0}]
    kept = d._apply_relevance_gate(markets, {}, 5.0)
    assert [m["market_id"] for m in kept] == ["b", "a"]  # 无分 → 全保留，按 volume 降序
    assert all("relevance_score" not in m for m in kept)


def test_market_env_uses_canonical_relevance_and_per_query_names(monkeypatch):
    monkeypatch.setenv("PM_MIN_RELEVANCE", "2")
    monkeypatch.setenv("PREDICTION_MARKETS_MIN_RELEVANCE", "7")
    monkeypatch.setenv("PREDICTION_MARKETS_PER_QUERY", "17")
    assert d._pm_min_relevance() == 7.0
    assert d._pm_per_query() == 17


def test_market_snapshot_diagnostics_distinguish_transport_failure(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(d, "_polymarket_get", fail)
    diagnostics = {}
    assert d._pm_snapshot(["AI bubble", "US recession"], diagnostics=diagnostics) == []
    assert diagnostics == {
        "attempted_query_count": 2,
        "successful_query_count": 0,
        "transport_failure_count": 2,
        # TRANSPORT-DIAG: 无 error_class 附注的裸异常按类型名计数
        "transport_error_classes": {"RuntimeError": 2},
    }


def test_market_snapshot_diagnostics_carry_error_class_and_http_status(monkeypatch):
    """_polymarket_get 挂载的 error_class/http_status 逐 query 聚合进 diagnostics。"""
    def fail(*_args, **_kwargs):
        err = RuntimeError("polymarket GET /public-search failed: HTTP Error 403: Forbidden")
        err.error_class = "HTTPError"
        err.http_status = 403
        raise err

    monkeypatch.setattr(d, "_polymarket_get", fail)
    diagnostics = {}
    assert d._pm_snapshot(["AI bubble", "US recession"], diagnostics=diagnostics) == []
    assert diagnostics["transport_error_classes"] == {"HTTPError:403": 2}


# ---------------------------------------------------------------- transport hardening

class _FakeHTTPBody:
    """urlopen 上下文管理器形状的极小假响应。"""

    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def test_polymarket_get_sends_browser_ua_and_new_default_timeout(monkeypatch):
    """每个请求必须带浏览器形 User-Agent + Accept；无 env 旋钮时默认超时 8s。
    （真实事故差分：stdlib 默认 "Python-urllib/3.x" UA 被 Cloudflare 拦，41/41 全灭。）"""
    import urllib.request
    monkeypatch.delenv("PREDICTION_MARKETS_HTTP_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("PREDICTION_MARKETS_HTTP_ATTEMPTS", raising=False)
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["ua"] = req.get_header("User-agent")
        seen["accept"] = req.get_header("Accept")
        seen["timeout"] = timeout
        return _FakeHTTPBody({"events": []})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert d._polymarket_get("/public-search", {"q": "x"}) == {"events": []}
    assert seen["ua"].startswith("Mozilla/5.0")
    assert "AppleWebKit" in seen["ua"]
    assert seen["accept"] == "application/json"
    assert seen["timeout"] == 8.0                        # 默认超时 3s→8s


def test_polymarket_get_retries_transient_5xx_with_backoff_then_succeeds(monkeypatch):
    """瞬时 503 → 抖动退避一次后重试成功（默认 attempts 1→2）。"""
    import urllib.error
    import urllib.request
    monkeypatch.delenv("PREDICTION_MARKETS_HTTP_ATTEMPTS", raising=False)
    backoffs = []
    monkeypatch.setattr(d, "_polymarket_backoff", lambda attempt: backoffs.append(attempt))
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 503, "Service Unavailable", None, None)
        return _FakeHTTPBody({"events": [{"title": "Ev"}]})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    out = d._polymarket_get("/public-search", {"q": "x"})
    assert out == {"events": [{"title": "Ev"}]}
    assert len(calls) == 2                               # 默认恰好重试一次
    assert backoffs == [1]                               # 退避发生在重试前


def test_polymarket_get_exhaustion_attaches_error_class_and_status(monkeypatch):
    """重试耗尽 → RuntimeError 携带 error_class/http_status（诊断沿 _pm_snapshot 持久化）。"""
    import urllib.error
    import urllib.request
    monkeypatch.delenv("PREDICTION_MARKETS_HTTP_ATTEMPTS", raising=False)
    monkeypatch.setattr(d, "_polymarket_backoff", lambda attempt: None)
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 503, "Service Unavailable", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    try:
        d._polymarket_get("/public-search", {"q": "x"})
        raise AssertionError("expected RuntimeError")
    except RuntimeError as err:
        assert err.error_class == "HTTPError"
        assert err.http_status == 503
    assert len(calls) == 2

    # 非瞬时 4xx（如 Cloudflare 403）不重试，但状态照样挂载。
    calls.clear()

    def fake_403(req, timeout=None):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_403)
    try:
        d._polymarket_get("/public-search", {"q": "x"})
        raise AssertionError("expected RuntimeError")
    except RuntimeError as err:
        assert err.error_class == "HTTPError"
        assert err.http_status == 403
    assert len(calls) == 1

    # URLError（连接失败/超时）→ 重试后仍失败：类名挂载、无状态码。
    calls.clear()

    def fake_urlerror(req, timeout=None):
        calls.append(1)
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlerror)
    try:
        d._polymarket_get("/public-search", {"q": "x"})
        raise AssertionError("expected RuntimeError")
    except RuntimeError as err:
        assert err.error_class == "URLError"
        assert err.http_status is None
    assert len(calls) == 2


def test_collector_persists_transport_error_classes_in_status(tmp_path, monkeypatch):
    """刷新快照全灭 → prediction_markets.json status 必须带 transport_error_classes
    （真实事故只有失败计数、无错误类别，下次断网仍不可诊断——这是回归钉）。"""
    def fail(*_args, **_kwargs):
        err = RuntimeError("polymarket GET /public-search failed: HTTP Error 403: Forbidden")
        err.error_class = "HTTPError"
        err.http_status = 403
        raise err

    monkeypatch.setattr(d, "_polymarket_get", fail)
    monkeypatch.setattr(d, "_pm_resolve_queries", lambda *_args, **_kwargs: ["AI bubble"])
    monkeypatch.setattr(d, "score_market_relevance", lambda *_args, **_kwargs: {})
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "true")
    monkeypatch.setenv("PREDICTION_MARKETS_PRICE_HISTORY", "false")
    d._set_pm_transport_unavailable(False)

    class Log:
        def write(self, level, message):
            pass

    meta = {}
    d._collect_prediction_markets(
        tmp_path, "Will the AI investment boom unwind in 2026?", "report body",
        meta, Log(), model_name="test",
    )

    payload = json.loads((tmp_path / d.PREDICTION_MARKETS_FILENAME).read_text(encoding="utf-8"))
    assert payload["no_relevant_markets"] is True
    assert payload["status"]["empty_reason"] == "transport_failure"
    assert payload["status"]["transport_failure_count"] == 1
    assert payload["status"]["transport_error_classes"] == {"HTTPError:403": 1}


def test_collector_circuit_open_persists_prepass_error_classes(tmp_path, monkeypatch):
    """前置快照断网（circuit open）→ 跳过重复刷新，但落盘 status 带前置错误类别。"""
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "true")

    class Log:
        def write(self, level, message):
            pass

    d._set_pm_transport_unavailable(True, {"HTTPError:403": 16})
    try:
        meta = {}
        d._collect_prediction_markets(
            tmp_path, "Will X happen?", "report body", meta, Log(), model_name="test",
        )
    finally:
        d._set_pm_transport_unavailable(False)

    payload = json.loads((tmp_path / d.PREDICTION_MARKETS_FILENAME).read_text(encoding="utf-8"))
    assert payload["reason"] == "pre-pass transport circuit open"
    assert payload["status"]["empty_reason"] == "transport_failure"
    assert payload["status"]["transport_error_classes"] == {"HTTPError:403": 16}
    assert meta["prediction_markets_count"] == 0


# ---------------------------------------------------------------- PM-1 market normalization enrich

def test_normalize_market_enriches_event_url_and_signals():
    raw = {
        "id": "42", "question": "Will X happen?",
        "outcomes": '["Yes","No"]', "outcomePrices": '["0.30","0.70"]',
        "volume": 5000, "liquidity": 100, "closed": False,
        "endDate": "2026-11-03T00:00:00Z", "oneDayPriceChange": 0.05,
        "bestBid": 0.29, "bestAsk": 0.31,
    }
    row = d._pm_normalize_market(raw, matched_query="x", min_volume=200,
                                 event_title="US House", event_slug="us-house-2026")
    assert row["event_url"] == "https://polymarket.com/event/us-house-2026"
    assert row["end_date"].startswith("2026-11-03")
    assert row["one_day_price_change"] == 0.05
    assert row["best_bid"] == 0.29 and row["best_ask"] == 0.31


def test_normalize_market_missing_signals_degrade():
    raw = {
        "id": "1", "question": "Q?", "outcomes": '["Yes","No"]',
        "outcomePrices": '["0.5","0.5"]', "volume": 5000, "closed": False,
    }
    row = d._pm_normalize_market(raw, matched_query="x", min_volume=200)
    assert "event_url" not in row and "best_bid" not in row  # 缺失字段不写键


# ---------------------------------------------------------------- INT-2 URL / tool-arg validation

def test_is_valid_http_url():
    assert d._is_valid_http_url("https://example.com/a")
    assert d._is_valid_http_url("http://x.io")
    assert d._is_valid_http_url("https://en.wikipedia.org/wiki/AI")
    assert not d._is_valid_http_url("notaurl")
    assert not d._is_valid_http_url("ftp://x.com")
    assert not d._is_valid_http_url("https://")
    assert not d._is_valid_http_url("https://en")
    assert not d._is_valid_http_url("https://en.wikipedia.org")
    assert not d._is_valid_http_url("https://en.wikipedia.org/wiki/St")
    assert not d._is_valid_http_url("https://en.wikipedia.org/wiki/ASML_H")
    assert not d._is_valid_http_url("https://en.wikipedia.org/wiki/Anduril_")
    assert not d._is_valid_http_url("")


def test_repair_url():
    assert d._repair_url("polymarket.com/event/x") == "https://polymarket.com/event/x"
    assert d._repair_url("//cdn.x.com/a") == "https://cdn.x.com/a"
    assert d._repair_url("foo bar") == ""       # 含空格无法修复
    assert d._repair_url("just-a-word") == ""   # 非域名形状


def test_title_from_url_prefers_human_readable_content_slug():
    assert d._title_from_url(
        "https://en.wikipedia.org/wiki/AI_Action_Plan"
    ) == "AI Action Plan"
    assert d._title_from_url("https://example.com") == "example.com"


def test_validate_tool_args_web_search_query_len():
    _, ok, _ = d._validate_tool_args("web_search", {"query": "ab"})
    assert ok is False
    _, ok, _ = d._validate_tool_args("web_search", {"query": "abcd"})
    assert ok is True


def test_validate_tool_args_web_fetch_repairs_url():
    args, ok, _ = d._validate_tool_args("web_fetch", {"url": "polymarket.com/x"})
    assert ok is True and args["url"] == "https://polymarket.com/x"


def test_validate_tool_args_web_fetch_rejects_garbage():
    _, ok, why = d._validate_tool_args("web_fetch", {"url": "###"})
    assert ok is False and "scheme" in why


def test_validate_tool_args_passthrough_other_tools():
    args = {"path": "/tmp"}
    out, ok, _ = d._validate_tool_args("read_file", args)
    assert ok is True and out is args


# ---------------------------------------------------------------- INT-2 sources.json URL grounding

def test_merge_fetched_into_sources_drops_urlless_and_repairs():
    d._reset_fetched_sources()
    grounded, dropped = d.merge_fetched_into_sources([
        {"title": "no url", "url": ""},               # 无 URL → 丢
        {"title": "bare host", "url": "example.com/a"},  # 裸 host → 修复保留
        {"title": "good", "url": "https://good.org/x"},
    ])
    urls = {s["url"] for s in grounded}
    assert "https://example.com/a" in urls
    assert "https://good.org/x" in urls
    assert dropped >= 1  # 无 URL 的那条被丢


# ---------------------------------------------------------------- RQ-6 brief-drift detection

def test_detect_year_drift_flags_mismatch():
    drift = d._detect_year_drift(
        "Who wins the 2026 US midterms?",
        "The 2028 presidential race dominates. 2028 primaries. 2028 again everywhere.",
    )
    assert drift is not None
    assert drift["notes_year"] == "2028"
    assert drift["brief_years"] == ["2026"]


def test_detect_year_drift_no_mismatch_when_aligned():
    assert d._detect_year_drift(
        "Who wins the 2026 US midterms?",
        "The 2026 midterms with some 2024 historical context.",
    ) is None


def test_detect_year_drift_none_without_brief_year():
    assert d._detect_year_drift("Who wins the election?", "The 2028 race.") is None


# ---------------------------------------------------------------- PM-4 prompt injection plumbing

def test_market_pricing_block_injection_roundtrip():
    d._set_market_pricing_block("")
    assert d._market_pricing_prompt_block() == ""
    block = d._pm_render_pricing_block(
        [{"market_id": "1", "question": "Will X?", "implied_yes_prob": 0.42, "volume": 1000.0}],
        as_of="2026-07-06T00:00:00+00:00",
    )
    assert "42%" in block and "Will X?" in block
    d._set_market_pricing_block(block)
    prompt = d.build_research_prompt("some question", "standard", None)
    assert "Will X?" in prompt and "42%" in prompt
    d._set_market_pricing_block("")  # 复位，勿泄漏到其它测试


# ================================================================ SCALE-5 / RQ-3 / PM-6 pure helpers

# ---------------------------------------------------------------- SCALE-5 universal source tiering

def test_universal_tiering_fills_fetched_default_s3(monkeypatch):
    """域名表命不中、模型也没给 tier 的**已抓取**来源 → 拿基线 tier（默认 S3），而非留 untiered。"""
    monkeypatch.delenv("RESEARCH_UNIVERSAL_TIERING", raising=False)
    monkeypatch.delenv("RESEARCH_DEFAULT_SOURCE_TIER", raising=False)
    d._reset_fetched_sources()
    d._merge_pending_fetches([{"url": "https://unknown-domain-xyz.example/a", "ok": True}])
    grounded, _dropped = d.merge_fetched_into_sources([])  # 无模型来源
    row = next(r for r in grounded if "unknown-domain-xyz.example" in r["url"])
    assert row["source_origin"] == "fetched"
    assert row["tier"] == "S3"
    d._reset_fetched_sources()


def test_universal_tiering_off_keeps_untiered(monkeypatch):
    """RESEARCH_UNIVERSAL_TIERING=false → untiered 抓取源保持无 tier（旧行为）。"""
    monkeypatch.setenv("RESEARCH_UNIVERSAL_TIERING", "false")
    d._reset_fetched_sources()
    d._merge_pending_fetches([{"url": "https://unknown-domain-xyz.example/b", "ok": True}])
    grounded, _ = d.merge_fetched_into_sources([])
    row = next(r for r in grounded if "unknown-domain-xyz.example" in r["url"])
    assert str(row.get("tier") or "").strip().upper() not in ("S1", "S2", "S3", "S4")
    d._reset_fetched_sources()


def test_universal_tiering_preserves_domain_and_model_tier(monkeypatch):
    """域名映射（congress.gov→S1）与模型自愿 tier 都胜过兜底默认（不被覆盖）。"""
    monkeypatch.setenv("RESEARCH_DEFAULT_SOURCE_TIER", "S2")
    d._reset_fetched_sources()
    d._merge_pending_fetches([
        {"url": "https://www.congress.gov/bill/x", "ok": True},      # S1 域名
        {"url": "https://random-blog.example/post", "ok": True},     # 未知域名 + 模型给 S1
    ])
    grounded, _ = d.merge_fetched_into_sources([
        {"url": "https://random-blog.example/post", "tier": "S1"},
    ])
    by = {r["url"]: r for r in grounded}
    gov = next(r for u, r in by.items() if "congress.gov" in u)
    assert gov["tier"] == "S1"           # 域名映射胜过默认 S2
    blog = next(r for u, r in by.items() if "random-blog.example" in u)
    assert blog["tier"] == "S1"          # 模型自愿 tier 保留，未被默认 S2 覆盖
    d._reset_fetched_sources()


def test_default_source_tier_rejects_s4_and_garbage(monkeypatch):
    monkeypatch.setenv("RESEARCH_DEFAULT_SOURCE_TIER", "S4")
    assert d._default_source_tier() == "S3"     # S4=reject-tier 不可作默认
    monkeypatch.setenv("RESEARCH_DEFAULT_SOURCE_TIER", "garbage")
    assert d._default_source_tier() == "S3"
    monkeypatch.setenv("RESEARCH_DEFAULT_SOURCE_TIER", "S1")
    assert d._default_source_tier() == "S1"
    monkeypatch.delenv("RESEARCH_DEFAULT_SOURCE_TIER", raising=False)
    assert d._default_source_tier() == "S3"     # 未设置 → S3


# ---------------------------------------------------------------- SCALE-5 adaptive-pass ceiling

def test_adaptive_passes_remaining_arithmetic():
    fixed = 1 + len(d.DEEP_RESEARCH_PHASES)          # 开场 + 固定相位
    assert d.adaptive_passes_remaining(0, 12) == 12 - fixed
    assert d.adaptive_passes_remaining(2, 12) == 12 - fixed - 2
    # 覆盖轮 + 固定 已 >= 总上限 → 0（绝不为负）
    assert d.adaptive_passes_remaining(10, 12) == 0
    # 总上限低于固定 pass → 0
    assert d.adaptive_passes_remaining(0, fixed - 1) == 0
    # 坏输入 → 0（不抛）
    assert d.adaptive_passes_remaining("x", 12) == 0
    assert d.adaptive_passes_remaining(0, None) == 0


# ---------------------------------------------------------------- RQ-3 report-judge scorecard gate


def _passing_report_scorecard():
    return {
        "verdict": "PASS",
        "scores": dict.fromkeys(d._REPORT_JUDGE_DIMS, 5),
    }


def test_report_passes_rejects_malformed_or_incomplete_scorecards():
    valid_scores = dict.fromkeys(d._REPORT_JUDGE_DIMS, 5)
    malformed = (
        None,
        "not a dict",
        {},
        {"verdict": "PASS"},
        {"verdict": "PASS", "scores": []},
        {"verdict": "UNKNOWN", "scores": valid_scores},
    )
    for scorecard in malformed:
        assert d.report_passes(scorecard) is False


def test_report_passes_explicit_fail_is_authoritative():
    assert d.report_passes({"verdict": "FAIL"}) is False
    assert d.report_passes({
        "verdict": "FAIL",
        "scores": dict.fromkeys(d._REPORT_JUDGE_DIMS, 5),
        "gaps": ["citation evidence was stripped during finalization"],
    }) is False


def test_report_passes_requires_exact_finite_in_range_numeric_dimensions():
    valid = dict.fromkeys(d._REPORT_JUDGE_DIMS, 5)
    missing = dict(valid)
    missing.pop("base_rate_usage")
    invalid_scores = {
        "missing dimension": missing,
        "extra dimension": {**valid, "style": 5},
        "numeric string": {**valid, "base_rate_usage": "5"},
        "boolean": {**valid, "base_rate_usage": True},
        "nan": {**valid, "base_rate_usage": float("nan")},
        "positive infinity": {**valid, "base_rate_usage": float("inf")},
        "negative infinity": {**valid, "base_rate_usage": float("-inf")},
        "integer overflow": {**valid, "base_rate_usage": 10**400},
        "below range": {**valid, "base_rate_usage": -0.1},
        "above range": {**valid, "base_rate_usage": 5.1},
    }
    for case, scores in invalid_scores.items():
        assert d.report_passes({"verdict": "PASS", "scores": scores}) is False, case

    assert d.report_passes(_passing_report_scorecard()) is True


def test_report_judge_input_cap_is_explicit_and_cannot_pass(monkeypatch):
    monkeypatch.setattr(d, "_JUDGE_INPUT_CAP", 5)
    bounded, identity = d._report_judge_input("abcdefgh")
    scorecard = _passing_report_scorecard()
    scorecard["_judge_input"] = identity

    assert bounded == "abcde"
    assert identity == {
        "report_chars": 8,
        "input_chars": 5,
        "input_sha256": hashlib.sha256(b"abcde").hexdigest(),
        "truncated": True,
    }
    assert d.report_passes(scorecard) is False


def test_report_judge_default_envelope_covers_useful_deep_dossier():
    report = "x" * 350_000

    bounded, identity = d._report_judge_input(report)

    assert bounded == report
    assert identity["report_chars"] == len(report)
    assert identity["input_chars"] == len(report)
    assert identity["truncated"] is False


def test_report_passes_full_scorecard_gate():
    dims = d._REPORT_JUDGE_DIMS
    # 全 5 分 → PASS
    assert d.report_passes({"verdict": "PASS", "scores": dict.fromkeys(dims, 5)}) is True
    # 非关键维 = 3（无维 <3、四关键维 ≥4、均分 ≥4）→ 仍 PASS
    sc = dict.fromkeys(dims, 5)
    sc["quantitative_density"] = 3
    assert d.report_passes({"verdict": "PASS", "scores": sc}) is True
    # 关键维 <4 → FAIL
    sc2 = dict.fromkeys(dims, 5)
    sc2["thesis_specificity"] = 3
    assert d.report_passes({"verdict": "PASS", "scores": sc2}) is False
    # 任一维 <3 → FAIL
    sc3 = dict.fromkeys(dims, 5)
    sc3["quantitative_density"] = 2
    assert d.report_passes({"verdict": "PASS", "scores": sc3}) is False


def test_report_passes_strict_env(monkeypatch):
    """RESEARCH_REPORT_JUDGE_STRICT=true → 任一维 <4 即 FAIL。"""
    dims = d._REPORT_JUDGE_DIMS
    sc = dict.fromkeys(dims, 5)
    sc["length_vs_target"] = 3       # 非关键维 3，宽松模式本应 PASS
    monkeypatch.setenv("RESEARCH_REPORT_JUDGE_STRICT", "true")
    assert d.report_passes({"verdict": "PASS", "scores": sc}) is False
    monkeypatch.setenv("RESEARCH_REPORT_JUDGE_STRICT", "false")
    assert d.report_passes({"verdict": "PASS", "scores": sc}) is True


def test_report_judge_sees_citation_finalized_bytes(monkeypatch):
    """Citation coverage must be judged on the bytes that can actually ship."""
    seen = {}

    monkeypatch.setattr(
        d,
        "finalize_report_citations",
        lambda report, _plog: report + "\n\nFINALIZED REFERENCES",
    )

    def _judge(report, *_args, **_kwargs):
        seen["report"] = report
        return {"verdict": "PASS", "scores": dict.fromkeys(d._REPORT_JUDGE_DIMS, 5)}

    monkeypatch.setattr(d, "judge_research_report", _judge)

    class _Log:
        def write(self, *_args, **_kwargs):
            return None

    out = d.run_report_judge_refine(
        object(), "thread", "question", "deep", None, "model", "DRAFT", _Log()
    )

    assert seen["report"].endswith("FINALIZED REFERENCES")
    assert out == seen["report"]


def test_report_judge_rejudges_last_allowed_refine_on_exact_final_bytes(monkeypatch):
    """A FAIL-triggered final mutation must be finalized and judged before return."""
    monkeypatch.setenv("RESEARCH_REPORT_JUDGE_MAX_ROUNDS", "1")
    judge_inputs = []
    scorecards = [
        {
            "verdict": "FAIL",
            "scores": dict.fromkeys(d._REPORT_JUDGE_DIMS, 5),
            "gaps": ["add independent corroboration"],
        },
        _passing_report_scorecard(),
    ]

    def _finalize(report, _plog):
        return report.replace(" [DANGLING]", "").rstrip() + "\nCITATION-FINALIZED"

    def _judge(report, *_args, **_kwargs):
        judge_inputs.append(report)
        return scorecards.pop(0)

    monkeypatch.setattr(d, "finalize_report_citations", _finalize)
    monkeypatch.setattr(d, "judge_research_report", _judge)
    monkeypatch.setattr(d, "run_streamed_turn", lambda *_args, **_kwargs: "TOP-UP NOTES")
    monkeypatch.setattr(
        d,
        "run_incremental_report_patch",
        lambda _question, report, *_args, **_kwargs: report + "\nREFINED [DANGLING]",
    )

    class _Log:
        def write(self, *_args, **_kwargs):
            return None

    out = d.run_report_judge_refine(
        object(), "thread", "question", "deep", None, "model", "DRAFT", _Log()
    )

    assert len(judge_inputs) == 2
    assert judge_inputs[0] == "DRAFT\nCITATION-FINALIZED"
    assert out == judge_inputs[-1]
    assert out.endswith("REFINED\nCITATION-FINALIZED")
    assert "DANGLING" not in out


def test_report_refine_rolls_back_when_final_rejudge_is_incomplete(monkeypatch):
    monkeypatch.setenv("RESEARCH_REPORT_JUDGE_MAX_ROUNDS", "1")
    initial_fail = {
        "verdict": "FAIL",
        "scores": dict.fromkeys(d._REPORT_JUDGE_DIMS, 5),
        "gaps": ["add corroboration"],
    }
    incomplete_scores = dict.fromkeys(d._REPORT_JUDGE_DIMS, 5)
    incomplete_scores.pop("citation_coverage")
    scorecards = [
        initial_fail,
        {"verdict": "PASS", "scores": incomplete_scores},
    ]

    monkeypatch.setattr(
        d,
        "finalize_report_citations",
        lambda report, _plog: report.rstrip() + "\nCITATION-FINALIZED",
    )
    monkeypatch.setattr(
        d,
        "judge_research_report",
        lambda *_args, **_kwargs: scorecards.pop(0),
    )
    monkeypatch.setattr(d, "run_streamed_turn", lambda *_args, **_kwargs: "TOP-UP NOTES")
    monkeypatch.setattr(
        d,
        "run_incremental_report_patch",
        lambda _question, report, *_args, **_kwargs: report + "\nREFINED",
    )

    class _Log:
        def write(self, *_args, **_kwargs):
            return None

    out = d.run_report_judge_refine(
        object(), "thread", "question", "deep", None, "model", "DRAFT", _Log()
    )

    assert out == "DRAFT\nCITATION-FINALIZED"


def test_adopted_topup_persists_judge_for_exact_final_bytes(tmp_path, monkeypatch):
    current = "BASE REPORT\n"
    (tmp_path / d.REPORT_FILENAME).write_text(current, encoding="utf-8")
    seen = []

    monkeypatch.setattr(
        d,
        "finalize_report_citations",
        lambda report, _plog: report.replace(" [DANGLING]", "").rstrip()
        + "\nCITATION-FINALIZED\n",
    )

    def _judge(report, *_args, **_kwargs):
        seen.append(report)
        scorecard = _passing_report_scorecard()
        scorecard["_judge_input"] = d._report_judge_input(report)[1]
        return scorecard

    monkeypatch.setattr(d, "judge_research_report", _judge)

    class _Log:
        def write(self, *_args, **_kwargs):
            return None

    meta = {"global_synthesis_judge": {"judged_prose_sha256": "stale"}}
    out, adopted = d._adopt_judged_report_candidate(
        tmp_path,
        current,
        "TOP-UP REPORT [DANGLING]",
        "question",
        None,
        "deep",
        "model",
        meta,
        _Log(),
        stage="triangulation-topup",
    )

    expected = "TOP-UP REPORT\nCITATION-FINALIZED\n"
    expected_hash = hashlib.sha256(expected.encode("utf-8")).hexdigest()
    persisted = json.loads(
        (tmp_path / "research_report_judge.json").read_text(encoding="utf-8")
    )

    assert adopted is True
    assert out == expected == seen[-1]
    assert (tmp_path / d.REPORT_FILENAME).read_text(encoding="utf-8") == expected
    assert persisted["_judged_prose"] == {
        "sha256": expected_hash,
        "chars": len(expected),
        "stage": "triangulation-topup",
        "scope": "llm-prose",
    }
    assert meta["research_report_judge"]["judged_prose_sha256"] == expected_hash
    assert meta["research_report_judge"]["judge_scope"] == "llm-prose"
    assert meta["research_report_judge"]["passed"] is True
    assert meta["global_synthesis_judge"]["judged_prose_sha256"] == expected_hash
    assert "report_sha256" not in meta["research_report_judge"]


def test_topup_explicit_fail_cannot_replace_current_report(tmp_path, monkeypatch):
    current = "BASE\n"
    (tmp_path / d.REPORT_FILENAME).write_text(current, encoding="utf-8")
    explicit_fail = {
        "verdict": "FAIL",
        "scores": dict.fromkeys(d._REPORT_JUDGE_DIMS, 5),
        "gaps": ["still lacks independent evidence"],
    }
    monkeypatch.setattr(d, "finalize_report_citations", lambda report, _plog: report)
    monkeypatch.setattr(
        d,
        "judge_research_report",
        lambda *_args, **_kwargs: explicit_fail,
    )

    class _Log:
        def write(self, *_args, **_kwargs):
            return None

    meta = {}
    out, adopted = d._adopt_judged_report_candidate(
        tmp_path,
        current,
        "LONGER TOP-UP REPORT",
        "question",
        None,
        "deep",
        "model",
        meta,
        _Log(),
        stage="triangulation-topup",
    )

    assert adopted is False
    assert out == current
    assert (tmp_path / d.REPORT_FILENAME).read_text(encoding="utf-8") == current
    assert not (tmp_path / "research_report_judge.json").exists()
    assert meta == {}


def test_late_candidate_cannot_regress_a_passing_dimension(tmp_path, monkeypatch):
    current = "BASE PASSING REPORT\n"
    current_scorecard = _passing_report_scorecard()
    current_scorecard["_judged_prose"] = {
        "sha256": hashlib.sha256(current.encode("utf-8")).hexdigest(),
        "chars": len(current),
        "stage": "initial",
        "scope": "llm-prose",
    }
    (tmp_path / d.REPORT_FILENAME).write_text(current, encoding="utf-8")
    (tmp_path / "research_report_judge.json").write_text(
        json.dumps(current_scorecard), encoding="utf-8"
    )
    regressed = _passing_report_scorecard()
    regressed["scores"]["base_rate_usage"] = 4
    candidate = "LONGER BUT WEAKER TOP-UP REPORT\n"
    regressed["_judge_input"] = d._report_judge_input(candidate)[1]
    monkeypatch.setattr(d, "finalize_report_citations", lambda report, _plog: report)
    monkeypatch.setattr(
        d, "judge_research_report", lambda *_args, **_kwargs: regressed
    )

    class _Log:
        def write(self, *_args, **_kwargs):
            return None

    out, adopted = d._adopt_judged_report_candidate(
        tmp_path,
        current,
        candidate,
        "question",
        None,
        "deep",
        "model",
        {},
        _Log(),
        stage="triangulation-topup",
    )

    assert adopted is False
    assert out == current
    assert (tmp_path / d.REPORT_FILENAME).read_text(encoding="utf-8") == current


def test_persist_report_judge_requires_exact_untruncated_input_identity(tmp_path):
    report = "EXACT JUDGED REPORT\n"
    meta = {}
    missing = _passing_report_scorecard()
    assert d._persist_report_judge(
        tmp_path, report, missing, meta, stage="test"
    ) is False

    mismatched = _passing_report_scorecard()
    mismatched["_judge_input"] = d._report_judge_input("OTHER REPORT\n")[1]
    assert d._persist_report_judge(
        tmp_path, report, mismatched, meta, stage="test"
    ) is False

    exact = _passing_report_scorecard()
    exact["_judge_input"] = d._report_judge_input(report)[1]
    assert d._persist_report_judge(
        tmp_path, report, exact, meta, stage="test"
    ) is True


def test_topup_rolls_back_when_final_scorecard_is_incomplete(tmp_path, monkeypatch):
    current = "BASE REPORT\n"
    judge_path = tmp_path / "research_report_judge.json"
    (tmp_path / d.REPORT_FILENAME).write_text(current, encoding="utf-8")
    judge_path.write_text('{"existing": true}\n', encoding="utf-8")
    previous_meta = {
        "research_report_judge": {"judged_prose_sha256": "existing"},
        "global_synthesis_judge": {"judged_prose_sha256": "existing"},
    }
    meta = {key: dict(value) for key, value in previous_meta.items()}
    incomplete_scores = dict.fromkeys(d._REPORT_JUDGE_DIMS, 5)
    incomplete_scores.pop("citation_coverage")

    monkeypatch.setattr(d, "finalize_report_citations", lambda report, _plog: report)
    monkeypatch.setattr(
        d,
        "judge_research_report",
        lambda *_args, **_kwargs: {"verdict": "PASS", "scores": incomplete_scores},
    )

    class _Log:
        def write(self, *_args, **_kwargs):
            return None

    out, adopted = d._adopt_judged_report_candidate(
        tmp_path,
        current,
        "UNJUDGED TOP-UP",
        "question",
        None,
        "deep",
        "model",
        meta,
        _Log(),
        stage="triangulation-topup",
    )

    assert adopted is False
    assert out == current
    assert (tmp_path / d.REPORT_FILENAME).read_text(encoding="utf-8") == current
    assert judge_path.read_text(encoding="utf-8") == '{"existing": true}\n'
    assert meta == previous_meta


def test_topup_rolls_back_when_citation_finalization_fails(tmp_path, monkeypatch):
    current = "BASE REPORT\n"
    report_path = tmp_path / d.REPORT_FILENAME
    judge_path = tmp_path / "research_report_judge.json"
    report_path.write_text(current, encoding="utf-8")
    judge_path.write_text('{"existing": true}\n', encoding="utf-8")
    previous_meta = {
        "research_report_judge": {"judged_prose_sha256": "existing"},
    }
    meta = {key: dict(value) for key, value in previous_meta.items()}
    judge_called = False

    def _fail_finalize(*_args, **_kwargs):
        raise RuntimeError("citation finalizer unavailable")

    def _judge(*_args, **_kwargs):
        nonlocal judge_called
        judge_called = True
        return _passing_report_scorecard()

    monkeypatch.setattr(d, "finalize_report_citations", _fail_finalize)
    monkeypatch.setattr(d, "judge_research_report", _judge)

    class _Log:
        def write(self, *_args, **_kwargs):
            return None

    out, adopted = d._adopt_judged_report_candidate(
        tmp_path,
        current,
        "UNFINALIZED TOP-UP [S999]",
        "question",
        None,
        "deep",
        "model",
        meta,
        _Log(),
        stage="triangulation-topup",
    )

    assert adopted is False
    assert out == current
    assert judge_called is False
    assert report_path.read_text(encoding="utf-8") == current
    assert judge_path.read_text(encoding="utf-8") == '{"existing": true}\n'
    assert meta == previous_meta


def test_persisted_report_identity_tracks_later_deterministic_rewrite(tmp_path):
    prose = "FINAL JUDGED PROSE\n"
    prose_hash = hashlib.sha256(prose.encode("utf-8")).hexdigest()
    report_path = tmp_path / d.REPORT_FILENAME
    report_path.write_text(prose, encoding="utf-8")
    meta = {
        "research_report_judge": {
            "judged_prose_sha256": prose_hash,
            "judge_scope": "llm-prose",
        }
    }

    assert d._record_persisted_report_identity(tmp_path, meta) is True
    assert meta["persisted_report_sha256"] == prose_hash

    with_annex = prose + "\n## Visual Annex\n\n![Chart](charts/chart.png)\n"
    report_path.write_text(with_annex, encoding="utf-8")
    assert d._record_persisted_report_identity(tmp_path, meta) is True

    assert meta["persisted_report_sha256"] == hashlib.sha256(
        with_annex.encode("utf-8")
    ).hexdigest()
    assert meta["research_report_judge"]["judged_prose_sha256"] == prose_hash
    assert meta["report_chars"] == len(with_annex)


def test_build_report_judge_prompt_is_json_only():
    p = d.build_report_judge_prompt("Will X happen in 2026?", None, "15,000–25,000 words")
    assert "thesis_specificity" in p and "citation_coverage" in p
    assert "PASS|FAIL" in p and "JSON" in p


# ---------------------------------------------------------------- PM-6 price-history parse










def test_tool_candidate_loader_skips_bad_lines_and_keeps_latest_quote(tmp_path):
    path = tmp_path / d.PREDICTION_MARKET_CANDIDATES_FILENAME
    path.write_text(
        "not-json\n"
        + json.dumps({
            "captured_at": "2026-07-10T00:00:00Z", "queries": ["AI bubble"],
            "markets": [{"market_id": "691340", "implied_yes_prob": 0.10}],
        }) + "\n"
        + json.dumps({
            "captured_at": "2026-07-11T00:00:00Z", "queries": ["AI bubble 2026"],
            "markets": [{"market_id": "691340", "implied_yes_prob": 0.1545}],
        }) + "\n",
        encoding="utf-8",
    )

    rows = d._load_tool_market_candidates(tmp_path)

    assert len(rows) == 1
    assert rows[0]["implied_yes_prob"] == 0.1545
    assert rows[0]["captured_via"] == "prediction_market_search"
    assert rows[0]["tool_queries"] == ["AI bubble 2026"]


def test_collector_preserves_report_vetted_tool_market_when_refresh_has_no_queries(
    tmp_path, monkeypatch,
):
    market = {
        "market_id": "691340",
        "question": "AI bubble burst in 2026?",
        "implied_yes_prob": 0.1545,
        "volume": 2_310_000.0,
        "url": "https://polymarket.com/event/ai-bubble-burst-in-2026",
        "end_date": "2026-12-31T00:00:00Z",
    }
    (tmp_path / d.PREDICTION_MARKET_CANDIDATES_FILENAME).write_text(
        json.dumps({
            "captured_at": "2026-07-11T00:00:00Z",
            "queries": ["AI bubble 2026"], "markets": [market],
        }) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(d, "_pm_resolve_queries", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(d, "score_market_relevance", lambda *_args, **_kwargs: {})
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "true")
    monkeypatch.setenv("PREDICTION_MARKETS_PRICE_HISTORY", "false")

    class Log:
        def __init__(self):
            self.rows = []

        def write(self, level, message):
            self.rows.append((level, message))

    meta = {}
    log = Log()
    report = "Our external calibration is Polymarket market 691340 at 15.45%."
    d._collect_prediction_markets(
        tmp_path, "Will the AI investment boom unwind in 2026?", report,
        meta, log, model_name="test",
    )

    payload = json.loads((tmp_path / d.PREDICTION_MARKETS_FILENAME).read_text(encoding="utf-8"))
    assert [row["market_id"] for row in payload["markets"]] == ["691340"]
    assert payload["status"]["tool_observation_count"] == 1
    assert payload["status"]["selected_count"] == 1
    assert payload["status"]["empty_reason"] is None
    assert meta["prediction_markets_count"] == 1
    assert "Prediction Market Signals" in (tmp_path / d.REPORT_FILENAME).read_text(encoding="utf-8")


def test_bridge_fanout_suppressed_when_harness_delegation_is_active(monkeypatch):
    monkeypatch.setattr(d, "_AGENTIC_DELEGATION", True)
    monkeypatch.setenv("RESEARCH_AGENTIC_SEARCH", "true")
    monkeypatch.setenv("RESEARCH_DEEP_FANOUT", "true")
    monkeypatch.delenv("RESEARCH_ALLOW_STACKED_FANOUT", raising=False)
    assert d._bridge_fanout_enabled() is False
    monkeypatch.setenv("RESEARCH_ALLOW_STACKED_FANOUT", "true")
    assert d._bridge_fanout_enabled() is True


def test_research_prompt_deterministically_activates_deep_research_skill():
    d._set_market_pricing_block("")
    prompt = d.build_research_prompt("Will X happen?", "standard", None)
    assert prompt.startswith("/deep-research\n")


# ---------------------------------------------------- i7: Yes 腿 token（LOOP-017 P1 收尾）

def test_pm_normalize_market_emits_yes_token_for_reversed_outcomes():
    """["No","Yes"] 排序的市场：clob_yes_token_id 必须按名定位（绝非下标 0），
    outcomes/outcome_prices 随行落盘（镜像 market_tools.normalize_market）。"""
    raw = {
        "id": "m-rev", "question": "Reversed outcome ordering?",
        "outcomes": '["No","Yes"]', "outcomePrices": '["0.875","0.125"]',
        "volume": "5000", "liquidity": "800",
        "clobTokenIds": '["tok-no","tok-yes"]',
    }
    row = d._pm_normalize_market(raw, matched_query="x", min_volume=200)
    assert row is not None
    assert row["outcomes"] == ["No", "Yes"]
    assert row["clob_token_ids"] == ["tok-no", "tok-yes"]
    assert row["clob_yes_token_id"] == "tok-yes"
    assert row["outcome_prices"] == [0.875, 0.125]
    assert row["implied_yes_prob"] == 0.125







def test_market_query_prompt_pins_today_and_future_only_rule():
    """PM-DATE（pipe_a19a0d5a4d39 复盘）：检索词派生提示词必须钉住今天的日期，
    并只允许检索「今天及以后才判定」的事件——此前模型按训练期年份派生出
    10/16 条 2025 已判定市场检索词，网络恢复也只会捞到已关闭市场。"""
    from datetime import date as _d
    prompt = d.build_market_queries_prompt(
        "forecast every FOMC decision through end-2026", None, None)
    assert _d.today().isoformat() in prompt
    assert "ON OR AFTER today" in prompt
    assert "already passed are resolved/closed" in prompt


def test_market_snapshot_deadline_hang_is_attributed(monkeypatch):
    """PM-NET：TLS/连接悬挂（无异常抛出、超死线未完成）必须显式归类——
    真实事故 16/16 查询全悬挂（SNI 阻断：TCP 可连、TLS 永不完成），
    payload 里 transport_failure_count=0 却被判 transport_failure，无可归因错误类。"""
    import time as _time

    def hang(*_args, **_kwargs):
        _time.sleep(2.5)
        return {}

    monkeypatch.setattr(d, "_polymarket_get", hang)
    monkeypatch.setenv("PREDICTION_MARKETS_DEADLINE_SECONDS", "1")
    diagnostics = {}
    assert d._pm_snapshot(["Fed decision December 2026", "Fed funds end-2026"],
                          diagnostics=diagnostics) == []
    assert diagnostics["attempted_query_count"] == 2
    assert diagnostics["successful_query_count"] == 0
    assert diagnostics.get("deadline_exhausted") == 1
    assert diagnostics["transport_error_classes"].get("DeadlineHang:tls-or-connect") == 2


def test_polymarket_base_urls_env_overridable():
    """PM-NET：SNI 阻断网络下可把 Gamma/CLOB 指向本地代理/镜像路由。"""
    import subprocess
    env = dict(os.environ,
               PREDICTION_MARKETS_API_BASE="http://127.0.0.1:9/",
               PREDICTION_MARKETS_CLOB_BASE="http://127.0.0.1:8/")
    fixture = os.path.join(_REPO_ROOT, "backend", "tests", "fixtures", "market_endpoint_configuration.py")
    out = subprocess.run([sys.executable, "-B", fixture], capture_output=True,
                         text=True, env=env, check=True).stdout.strip()
    assert out == "http://127.0.0.1:9 http://127.0.0.1:8"
