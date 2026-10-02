"""预测市场集成（Polymarket 公开 Gamma API，keyless）的离线测试。

全部 mock httpx，绝不发真实请求：客户端解析/规整化/去重/降级、markdown 渲染、
检索词派生启发式、以及 forecast_extractor 的 market_anchor 贯通。
"""

import json
import time
from datetime import datetime, timezone

import httpx
import pytest

from app.utils import prediction_markets as pm
from app.utils.prediction_markets import (
    PolymarketClient,
    derive_market_queries,
    derive_market_queries_llm,
    render_markets_block,
    score_market_relevance,
)
from app.services.forecast_extractor import (
    derive_forecast_spine,
    extract_binary_forecasts,
    render_binary_forecasts_block,
)
from tests.conftest import FakeLLMClient

# import 时捕获真实退避函数（autouse fixture 会把 pm._backoff_sleep 换成 no-op 提速）。
_REAL_BACKOFF_SLEEP = pm._backoff_sleep


# ---------------------------------------------------------------- helpers

class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            # response=self 镜像真实 httpx：异常携带 .response.status_code（诊断持久化读取）。
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=self)

    def json(self):
        return self._payload


def _raw(mid, vol=1000, liq=50, yes="0.2100", closed=False,
         outcomes='["Yes","No"]', prices=None, **kw):
    """一条 Polymarket /public-search 里嵌套的 market 行（字符串价，镜像真实 API）。"""
    if prices is None:
        prices = json.dumps([yes, f"{1 - float(yes):.4f}"])
    d = {
        "id": mid, "question": f"Will {mid} resolve yes?",
        "outcomes": outcomes, "outcomePrices": prices,
        "volume": vol, "liquidity": liq, "closed": closed, "active": True,
        "groupItemTitle": "",
    }
    d.update(kw)
    return d


def _event(title, markets):
    return {"title": title, "slug": "s", "markets": markets}


def _payload(events):
    return {"events": events, "pagination": {}}


@pytest.fixture
def enabled(monkeypatch):
    """打开 PREDICTION_MARKETS_ENABLED（覆盖 conftest 的 autouse 关闭），使 client.enabled=True。"""
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "true")
    from app.config import Config
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    """瞬时错误重试退避在测试里 no-op（保持套件秒级）；需要断言退避的测试自行覆盖。"""
    monkeypatch.setattr(pm, "_backoff_sleep", lambda attempt: None)


# ---------------------------------------------------------------- client

def test_disabled_makes_no_http_call(monkeypatch):
    """默认（conftest）关闭时：client.enabled=False，绝不发请求。"""
    calls = []
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: calls.append(1))
    client = PolymarketClient()
    assert client.enabled is False
    assert client.search_events("tariff") == []
    assert client.snapshot_for_queries(["tariff"]) == []
    assert calls == []  # 未启用时绝不发请求


def test_search_events_parses_and_keyless(enabled, monkeypatch):
    seen = {}

    def fake_get(url, params=None, timeout=None, headers=None):
        seen.update(url=url, params=params, headers=headers, timeout=timeout)
        return FakeResponse(_payload([_event("Ev", [_raw("m1")]), "not-a-dict"]))

    monkeypatch.setattr(pm.httpx, "get", fake_get)
    out = PolymarketClient().search_events("tariff", limit=5)
    assert [e["title"] for e in out] == ["Ev"]           # 非 dict 事件被丢弃
    assert seen["url"].endswith("/public-search")
    assert seen["params"] == {"q": "tariff", "limit_per_type": 5,
                              "events_status": "active"}
    assert "X-API-Key" not in seen["headers"]            # keyless：不发鉴权头
    assert seen["timeout"] == 10.0                       # 默认超时 15s→10s（transport 加固）
    # Cloudflare 拦/降权编程 UA → 必须发浏览器形 User-Agent（真实断网事故的差分根因）
    assert seen["headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert "AppleWebKit" in seen["headers"]["User-Agent"]
    assert seen["headers"]["Accept"] == "application/json"


def test_transport_error_retries_once_then_degrades_to_empty(enabled, monkeypatch):
    calls = []

    def fake_get(*a, **k):
        calls.append(1)
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(pm.httpx, "get", fake_get)
    assert PolymarketClient().search_events("tariff") == []
    assert len(calls) == 2  # 瞬时错误恰好重试一次，然后降级为空（绝不抛）


def test_transient_5xx_retries_then_succeeds(enabled, monkeypatch):
    responses = [FakeResponse(status_code=503),
                 FakeResponse(_payload([_event("Ev", [_raw("m1")])]))]
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: responses.pop(0))
    out = PolymarketClient().search_events("tariff")
    assert [e["title"] for e in out] == ["Ev"]


def test_non_transient_4xx_does_not_retry(enabled, monkeypatch):
    calls = []

    def fake_get(*a, **k):
        calls.append(1)
        return FakeResponse(status_code=404)

    monkeypatch.setattr(pm.httpx, "get", fake_get)
    assert PolymarketClient().search_events("tariff") == []
    assert len(calls) == 1  # 4xx 不重试


def test_transient_retry_backs_off_with_jitter_before_second_attempt(enabled, monkeypatch):
    """瞬时 5xx → 第二次尝试前必须走抖动退避（_backoff_sleep(1)）；成功后不再退避。"""
    backoffs = []
    monkeypatch.setattr(pm, "_backoff_sleep", lambda attempt: backoffs.append(attempt))
    responses = [FakeResponse(status_code=503),
                 FakeResponse(_payload([_event("Ev", [_raw("m1")])]))]
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: responses.pop(0))
    out = PolymarketClient().search_events("tariff")
    assert [e["title"] for e in out] == ["Ev"]
    assert backoffs == [1]                               # 恰好一次、发生在重试前


def test_backoff_sleep_is_jittered_and_bounded(monkeypatch):
    """真实退避函数：~0.5-1.0s（attempt=1）、带 random 抖动、上限 2.0+抖动。
    （autouse fixture 把 pm._backoff_sleep 换成 no-op，这里直捣 import 时捕获的原函数。）"""
    slept = []
    monkeypatch.setattr(pm.time, "sleep", lambda s: slept.append(s))
    _REAL_BACKOFF_SLEEP(1)
    _REAL_BACKOFF_SLEEP(10)                              # 大 attempt 也被 2.0s 基数封顶
    assert 0.5 <= slept[0] <= 1.0
    assert 2.0 <= slept[1] <= 2.5


def test_exhausted_transient_5xx_records_error_class_and_status(enabled, monkeypatch):
    """重试仍 5xx → 降级为空，但错误类名 + HTTP 状态 additive 落在 client 上（可持久化诊断）。"""
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: FakeResponse(status_code=503))
    client = PolymarketClient()
    assert client.search_events("tariff") == []
    assert client.last_error["error_class"] == "HTTPStatusError"
    assert client.last_error["http_status"] == 503
    assert client.last_error["url"].endswith("/public-search")
    assert client.transport_errors == {"HTTPStatusError:503": 1}


def test_connect_error_records_error_class_without_status(enabled, monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(pm.httpx, "get", boom)
    client = PolymarketClient()
    assert client.search_events("tariff") == []
    assert client.last_error["error_class"] == "ConnectError"
    assert client.last_error["http_status"] is None
    assert client.transport_errors == {"ConnectError": 1}


def test_non_transient_4xx_records_status_and_errors_accumulate(enabled, monkeypatch):
    """404（Cloudflare 拦截常见形态是 403）不重试，但状态码必须被记录；计数跨请求累计。"""
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: FakeResponse(status_code=404))
    client = PolymarketClient()
    assert client.search_events("tariff") == []
    assert client.search_events("recession") == []
    assert client.last_error["error_class"] == "HTTPStatusError"
    assert client.last_error["http_status"] == 404
    assert client.transport_errors == {"HTTPStatusError:404": 2}


def test_success_leaves_no_transport_error_records(enabled, monkeypatch):
    monkeypatch.setattr(pm.httpx, "get",
                        lambda *a, **k: FakeResponse(_payload([_event("Ev", [_raw("m1")])])))
    client = PolymarketClient()
    assert client.search_events("tariff")
    assert client.last_error is None
    assert client.transport_errors == {}


# ------------------------------------------------------------- snapshot

def test_snapshot_normalizes_filters_dedupes_and_sorts(enabled, monkeypatch):
    by_query = {
        "tariff": _payload([
            _event("Big", [_raw("m-big", vol=9000, yes="0.6400")]),
            _event("Bad", [
                _raw("m-closed", vol=8000, closed=True),                    # 已关闭 → 剔除
                _raw("m-resolved", vol=8000, prices='["1","0"]'),           # 价=1 定盘 → 剔除
                _raw("m-thin", vol=50),                                     # 低于 min_volume → 剔除
                _raw("m-noprice", vol=5000, prices='["","x"]'),            # 无可解析价 → 剔除
            ]),
        ]),
        "semiconductor export": _payload([
            _event("Big", [_raw("m-big", vol=9000, yes="0.6400")]),         # 跨 query 重复 → 去重
            _event("Small", [_raw("m-small", vol=500, yes="0.2100")]),
        ]),
    }

    def fake_get(url, params=None, timeout=None, headers=None):
        return FakeResponse(by_query[params["q"]])

    monkeypatch.setattr(pm.httpx, "get", fake_get)
    out = PolymarketClient().snapshot_for_queries(
        ["tariff", "semiconductor export"], min_volume=200)
    assert [m["market_id"] for m in out] == ["m-big", "m-small"]  # volume 降序
    big = out[0]
    assert big["implied_yes_prob"] == 0.64          # "0.6400" 字符串 → float
    assert big["matched_query"] == "tariff"          # 首个命中的 query
    assert big["exchange"] == "polymarket"
    assert big["event_title"] == "Big"               # 事件标题回填
    assert out[1]["matched_query"] == "semiconductor export"


def test_snapshot_max_total_cap_and_query_failure_isolation(enabled, monkeypatch):
    def fake_get(url, params=None, timeout=None, headers=None):
        if params["q"] == "bad":
            raise httpx.ConnectError("down")
        return FakeResponse(_payload([
            _event("E", [_raw(f"m{i}-{params['q']}", vol=1000 + i) for i in range(5)])]))

    monkeypatch.setattr(pm.httpx, "get", fake_get)
    out = PolymarketClient().snapshot_for_queries(["a", "bad", "b"], max_total=3)
    assert len(out) == 3                            # 限量
    assert all("bad" not in m["market_id"] for m in out)  # 失败 query 只丢那一批


def test_snapshot_caps_markets_per_event_for_diversity(enabled, monkeypatch):
    """一个多结局事件的高成交量子市场阶梯不得霸占全部名额——每事件默认最多 3 条，
    其余名额留给其他事件（用户诉求：surface 多个不同事件的市场，而非一个事件的阶梯）。"""
    ladder = [_raw(f"cut{i}", vol=9000 - i, yes="0.01") for i in range(8)]   # 同一事件 8 个子市场
    payload = _payload([
        _event("Fed rate cuts count", ladder),
        _event("House control", [_raw("house", vol=100, yes="0.55")]),        # 另一事件（低量）
    ])
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: FakeResponse(payload))
    out = PolymarketClient().snapshot_for_queries(["x"], min_volume=50, max_per_event=3)
    fed = [m for m in out if m["event_title"] == "Fed rate cuts count"]
    assert len(fed) == 3                                    # 阶梯被限到 3 条
    assert any(m["event_title"] == "House control" for m in out)  # 其他事件仍能露出
    # max_per_event<=0 → 不限制
    unlimited = PolymarketClient().snapshot_for_queries(["x"], min_volume=50, max_per_event=0)
    assert len([m for m in unlimited if m["event_title"] == "Fed rate cuts count"]) == 8


def test_snapshot_yes_price_by_outcome_index(enabled, monkeypatch):
    """outcomes 顺序颠倒时，仍按 "Yes" 的下标取价，而非盲取第一个。"""
    payload = _payload([_event("E", [
        _raw("m-rev", vol=3000, outcomes='["No","Yes"]', prices='["0.30","0.70"]')])])
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: FakeResponse(payload))
    out = PolymarketClient().snapshot_for_queries(["x"])
    assert out[0]["implied_yes_prob"] == 0.70       # 取 "Yes"（下标 1）而非 0.30


def test_snapshot_per_query_limit_widened_to_15_and_knob(enabled, monkeypatch):
    """每词 limit_per_type 从 8 放宽到 15（默认），且尊重 PREDICTION_MARKETS_PER_QUERY 旋钮。"""
    seen = {}

    def fake_get(url, params=None, timeout=None, headers=None):
        seen["params"] = params
        return FakeResponse(_payload([]))

    monkeypatch.setattr(pm.httpx, "get", fake_get)
    client = PolymarketClient()
    client.snapshot_for_queries(["tariff"])
    assert seen["params"]["limit_per_type"] == 15   # 新默认（8→15）
    client.search_events("tariff")
    assert seen["params"]["limit_per_type"] == 15   # search_events 默认同步放宽
    from app.config import Config
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_PER_QUERY", 7, raising=False)
    client.snapshot_for_queries(["tariff"])
    assert seen["params"]["limit_per_type"] == 7    # 旋钮生效
    client.snapshot_for_queries(["tariff"], per_query=4)
    assert seen["params"]["limit_per_type"] == 4    # 显式入参优先于旋钮


def test_normalize_enrichment_url_enddate_and_book(enabled, monkeypatch):
    """API 行带 endDate/oneDayPriceChange/bestBid/bestAsk、事件带 slug 时富化输出；
    缺失字段不造假（键不出现）。"""
    # TIME-3: render_markets_block compares endDate against market_clock_now(); pin it so the
    # rendered bytes never depend on the wall clock (2026-12-31 has not passed on 2026-10-01).
    monkeypatch.setattr(pm, "market_clock_now", lambda: datetime(2026, 10, 1, tzinfo=timezone.utc))
    rich = _raw("m-rich", vol=5000, yes="0.4000", endDate="2026-12-31T00:00:00Z",
                oneDayPriceChange="-0.021", bestBid=0.39, bestAsk="0.41")
    lean = _raw("m-lean", vol=4000, yes="0.3000")
    payload = {"events": [
        {"title": "Ev", "slug": "us-tariffs-2026", "markets": [rich]},
        {"title": "Lean", "slug": "", "markets": [lean]},
    ], "pagination": {}}
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: FakeResponse(payload))
    out = PolymarketClient().snapshot_for_queries(["x"])
    by = {m["market_id"]: m for m in out}
    r = by["m-rich"]
    assert r["url"] == "https://polymarket.com/event/us-tariffs-2026"  # 事件 slug → URL
    assert r["end_date"] == "2026-12-31T00:00:00Z"
    assert r["one_day_price_change"] == -0.021       # 字符串数值 → float
    assert r["best_bid"] == 0.39 and r["best_ask"] == 0.41
    for key in ("url", "end_date", "one_day_price_change", "best_bid", "best_ask"):
        assert key not in by["m-lean"]               # 缺失不造假
    block = render_markets_block(out, lang="en")     # 渲染把问题变成可点链接
    assert "[Will m-rich resolve yes?](https://polymarket.com/event/us-tariffs-2026)" in block
    assert "| 2 | Will m-lean resolve yes? (m-lean) |" in block  # 无 URL 行保持旧格式
    assert "window ended" not in block               # endDate 未过（钉住的时钟）→ 不打标


# ------------------------------------------------------------- requote

def test_requote_markets_merges_fresh_prices_and_flags_failures(enabled, monkeypatch):
    """批量重报价：拉当前价覆盖 implied_yes_prob、保留研究期价、算 price_delta；
    已关闭 / 未返回的市场保留旧价并标 requote_failed=True，传入行不被原地污染。"""
    seen = {}

    def fake_get(url, params=None, timeout=None, headers=None):
        seen.update(url=url, params=params)
        return FakeResponse([
            _raw("m1", yes="0.4100"),                    # 现价 0.41（研究期 0.34）
            _raw("m2", yes="0.2000", closed=True),        # 已关闭 → requote_failed
        ])

    monkeypatch.setattr(pm.httpx, "get", fake_get)
    markets = [
        {"market_id": "m1", "exchange": "polymarket", "question": "Q1",
         "implied_yes_prob": 0.34, "volume": 9000},
        {"market_id": "m2", "exchange": "polymarket", "question": "Q2",
         "implied_yes_prob": 0.55, "volume": 500},
        {"market_id": "m3", "exchange": "polymarket", "question": "Q3",
         "implied_yes_prob": 0.60, "volume": 100},        # 未在响应里 → requote_failed
    ]
    out = PolymarketClient().requote_markets(markets)
    assert seen["url"].endswith("/markets")
    assert seen["params"] == {"id": ["m1", "m2", "m3"]}   # 批量重复 id 参数
    by = {m["market_id"]: m for m in out}
    m1 = by["m1"]
    assert m1["price_at_research"] == 0.34               # 研究期价被保留
    assert m1["implied_yes_prob"] == 0.41                # 现价覆盖
    assert m1["price_delta"] == round(0.41 - 0.34, 4)    # 分歧确定性计算
    assert "requote_failed" not in m1
    assert by["m2"]["implied_yes_prob"] == 0.55          # 已关闭 → 保留旧价
    assert by["m2"]["price_at_research"] == 0.55
    assert by["m2"]["requote_failed"] is True
    assert "price_delta" not in by["m2"]
    assert by["m3"]["implied_yes_prob"] == 0.60          # 未返回 → 保留旧价
    assert by["m3"]["requote_failed"] is True
    assert all("price_at_research" not in m for m in markets)  # 传入行不被污染


def test_requote_markets_disabled_and_empty_and_idempotent(monkeypatch):
    """未启用 → 不发请求、各行标 requote_failed 但保留旧价；空输入 → []；
    幂等重入：已有 price_at_research 时沿用（不把上一轮的现价误当研究期价）。"""
    calls = []
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: calls.append(1))
    assert PolymarketClient().requote_markets([]) == []
    assert PolymarketClient().requote_markets(None) == []
    out = PolymarketClient().requote_markets([
        {"market_id": "m1", "implied_yes_prob": 0.40}])   # conftest 默认关闭
    assert out[0]["requote_failed"] is True
    assert out[0]["implied_yes_prob"] == 0.40             # 旧价保留
    assert out[0]["price_at_research"] == 0.40
    assert calls == []                                    # 未启用绝不发请求
    # 幂等：已带 price_at_research 的行再次重报价失败时，研究期价不被现价覆盖。
    out2 = PolymarketClient().requote_markets([
        {"market_id": "m1", "implied_yes_prob": 0.48, "price_at_research": 0.34}])
    assert out2[0]["price_at_research"] == 0.34


def test_requote_markets_transport_failure_degrades_to_flag(enabled, monkeypatch):
    """取数网络失败（重试后仍失败）→ 各行标 requote_failed、保留旧价，绝不抛。"""
    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(pm.httpx, "get", boom)
    out = PolymarketClient().requote_markets([
        {"market_id": "m1", "implied_yes_prob": 0.40, "volume": 100}])
    assert out[0]["requote_failed"] is True
    assert out[0]["implied_yes_prob"] == 0.40


# ------------------------------------------------------------- price history

def test_fetch_price_history_parses_and_degrades(enabled, monkeypatch):
    """解析 {"history": [{t, p}]} → [{t, p}]（脏点跳过）；命中正确的 clob 宿主与参数。"""
    seen = {}

    def fake_get(url, params=None, timeout=None, headers=None):
        seen.update(url=url, params=params)
        return FakeResponse({"history": [
            {"t": 1750000000, "p": "0.41"},              # 字符串价 → float
            {"t": 1750086400, "p": 0.43},
            {"t": 1750172800, "p": "bad"},               # 不可解析价 → 跳过
            {"p": 0.5},                                  # 缺时间戳 → 跳过
        ]})

    monkeypatch.setattr(pm.httpx, "get", fake_get)
    out = PolymarketClient().fetch_price_history("0xTOKEN", interval="1d", days=0)
    assert seen["url"] == "https://clob.polymarket.com/prices-history"  # CLOB 宿主
    assert seen["params"] == {"market": "0xTOKEN", "interval": "1d"}     # keyless
    assert out == [{"t": 1750000000, "p": 0.41}, {"t": 1750086400, "p": 0.43}]

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(pm.httpx, "get", boom)
    assert PolymarketClient().fetch_price_history("0xTOKEN") == []       # 网络失败 → []
    assert PolymarketClient().fetch_price_history("") == []              # 空 token → []


def test_fetch_price_history_disabled_makes_no_call(monkeypatch):
    """未启用（conftest 默认）→ 不发请求、返回 []。"""
    calls = []
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: calls.append(1))
    assert PolymarketClient().fetch_price_history("0xTOKEN") == []
    assert calls == []


def test_fetch_price_history_trims_by_days(enabled, monkeypatch):
    """days>0 → 客户端裁剪，只保留最近 days 天的点。"""
    now = time.time()
    old = int(now - 100 * 86400)
    recent = int(now - 10 * 86400)
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: FakeResponse(
        {"history": [{"t": old, "p": "0.30"}, {"t": recent, "p": "0.40"}]}))
    out = PolymarketClient().fetch_price_history("0xTOK", days=90)
    assert out == [{"t": recent, "p": 0.40}]             # 100 天前的点被 days=90 截掉


def test_normalize_preserves_clob_token_ids(enabled, monkeypatch):
    """规整化保留 Gamma 的 clobTokenIds（JSON 串 → list）；缺失不造假（键不出现）。"""
    payload = _payload([_event("Ev", [
        _raw("m-clob", vol=5000, yes="0.4000", clobTokenIds='["0xYES","0xNO"]'),
        _raw("m-noclob", vol=5000, yes="0.4000"),
    ])])
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: FakeResponse(payload))
    by = {m["market_id"]: m for m in PolymarketClient().snapshot_for_queries(["x"])}
    assert by["m-clob"]["clob_token_ids"] == ["0xYES", "0xNO"]
    assert "clob_token_ids" not in by["m-noclob"]        # 缺失不造假


# ------------------------- LOOP-017 P1: reversed-token（outcomes 顺序颠倒）红线
# Gamma 的 clobTokenIds 与 outcomes **位置对齐**；市场偶有 ["No","Yes"] 排序。任何
# 消费方（历史价时间线取 Yes 腿）都不得假设下标 0 是 Yes——快照行必须带 outcomes 原
# 名单 + 显式的 clob_yes_token_id（按 "Yes" 下标定位），令位置假设从数据层面失效。
def test_normalize_reversed_outcomes_selects_yes_token_by_name(enabled, monkeypatch):
    payload = _payload([_event("Ev", [
        _raw("m-rev", vol=5000, outcomes='["No","Yes"]', prices='["0.30","0.70"]',
             clobTokenIds='["0xNO","0xYES"]'),
        _raw("m-norm", vol=5000, outcomes='["Yes","No"]', prices='["0.40","0.60"]',
             clobTokenIds='["0xY","0xN"]'),
    ])])
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: FakeResponse(payload))
    by = {m["market_id"]: m for m in PolymarketClient().snapshot_for_queries(["x"])}
    rev = by["m-rev"]
    assert rev["implied_yes_prob"] == 0.70               # 价按 "Yes" 名定位（回归钉）
    assert rev["clob_token_ids"] == ["0xNO", "0xYES"]    # 原始位置序保留（与 outcomes 对齐）
    assert rev["outcomes"] == ["No", "Yes"]              # 名单落盘 → 对齐可解释
    assert rev["clob_yes_token_id"] == "0xYES"           # Yes 腿按名定位，绝非下标 0
    assert by["m-norm"]["clob_yes_token_id"] == "0xY"    # 正常序同样正确


def test_normalize_no_outcomes_never_fabricates_yes_token(enabled, monkeypatch):
    """outcomes 缺失/长度不齐时绝不猜 Yes 腿（键不出现）；clob_token_ids 原样保留。"""
    payload = _payload([_event("Ev", [
        # 长度不齐：3 个 token、2 个结局名 → Yes 下标虽在，但保守要求下标落在 token 范围内。
        _raw("m-short", vol=5000, outcomes='["No","Yes"]', prices='["0.30","0.70"]',
             clobTokenIds='["0xONLY"]'),
    ])])
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: FakeResponse(payload))
    by = {m["market_id"]: m for m in PolymarketClient().snapshot_for_queries(["x"])}
    row = by["m-short"]
    assert row["clob_token_ids"] == ["0xONLY"]
    assert "clob_yes_token_id" not in row                # Yes 下标 1 超出 token 列表 → 不造假


def test_parse_resolution_reversed_outcomes_by_name():
    """判定终态解析按结局**名**定位（钉住证明）：outcomes 颠倒时 resolved_outcome 与
    resolved_yes_price 仍正确——"No" 胜出时 Yes 终价 ~0，反之 ~1。纯函数、无网络。"""
    no_won = pm._parse_resolution({
        "id": "m1", "closed": True,
        "outcomes": '["No","Yes"]', "outcomePrices": '["0.995","0.005"]'})
    assert no_won["resolved"] is True
    assert no_won["resolved_outcome"] == "No"
    assert no_won["resolved_yes_price"] == 0.005         # Yes 名定位（下标 1），非位置 0
    yes_won = pm._parse_resolution({
        "id": "m2", "closed": True,
        "outcomes": '["No","Yes"]', "outcomePrices": '["0.004","0.996"]'})
    assert yes_won["resolved_outcome"] == "Yes"
    assert yes_won["resolved_yes_price"] == 0.996


def test_fresh_yes_price_reversed_outcomes_by_name():
    """重报价路径同样按名取 "Yes" 价（钉住证明）：颠倒序返回 Yes 腿现价。"""
    assert pm._fresh_yes_price({
        "id": "m", "closed": False,
        "outcomes": '["No","Yes"]', "outcomePrices": '["0.30","0.70"]'}) == 0.70


def test_render_markets_block_shows_delta_column_on_requote():
    """重报价后有价格移动 → 追加 Δ 列（34%→41%）；未移动的行留占位符；
    无 price_at_research → 不加 Δ 列（与旧渲染一致）。"""
    markets = [
        {"market_id": "m1", "exchange": "polymarket", "question": "Q1",
         "implied_yes_prob": 0.41, "price_at_research": 0.34, "price_delta": 0.07,
         "volume": 9000},
        {"market_id": "m2", "exchange": "polymarket", "question": "Q2",
         "implied_yes_prob": 0.50, "price_at_research": 0.50, "volume": 500},  # 未变动
    ]
    block = render_markets_block(markets, lang="en")
    assert "Δ (research→now)" in block
    assert "34%→41%" in block
    m2_line = next(l for l in block.splitlines() if l.startswith("| 2 |"))
    assert "→" not in m2_line                            # 未变动行 Δ 为占位符
    # 无 price_at_research → 不加 Δ 列，逐字节与旧渲染一致
    plain = render_markets_block([{"market_id": "m1", "exchange": "polymarket",
                                   "question": "Q", "implied_yes_prob": 0.4, "volume": 100}])
    assert "Δ" not in plain
    assert "| 1 | Q (m1) | polymarket | 40% | 100 |" in plain
    zh = render_markets_block(markets, lang="zh")
    assert "Δ（研究→现在）" in zh and "34%→41%" in zh


# ------------------------------------------------------- relevance scoring

def _rel_markets():
    return [
        {"market_id": "m1", "exchange": "polymarket", "question": "Sports parlay hits?",
         "implied_yes_prob": 0.5, "volume": 9000, "liquidity": 10,
         "event_title": "Sports", "matched_query": "fed"},
        {"market_id": "m2", "exchange": "polymarket", "question": "Tariffs above 10%?",
         "implied_yes_prob": 0.3, "volume": 500, "liquidity": 10,
         "event_title": "Tariffs", "matched_query": "tariff"},
        {"market_id": "m3", "exchange": "polymarket", "question": "Export controls tighten?",
         "implied_yes_prob": 0.6, "volume": 8000, "liquidity": 10,
         "event_title": "Chips", "matched_query": "export"},
    ]


def test_score_market_relevance_gates_and_reranks(monkeypatch):
    from app.config import Config
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_MIN_RELEVANCE", 5.0, raising=False)
    prompts = []

    def llm(prompt):
        prompts.append(prompt)
        return json.dumps([
            {"market_id": "m1", "score": 2, "rationale": "sports, unrelated"},
            {"market_id": "m2", "score": 9, "rationale": "direct bet"},
            {"market_id": "m3", "score": 7, "rationale": "adjacent"},
        ])

    mkts = _rel_markets()
    out = score_market_relevance(llm, "Will tariffs rise?", mkts)
    assert len(prompts) == 1                                 # 单次批量调用
    assert "m1" in prompts[0] and "Tariffs above 10%?" in prompts[0]
    assert [m["market_id"] for m in out] == ["m2", "m3"]     # 相关性优先于 volume；m1 被门槛剔除
    assert out[0]["relevance_score"] == 9.0
    assert out[0]["relevance_rationale"] == "direct bet"
    assert all("relevance_score" not in m for m in mkts)     # 传入行不被原地污染（返回浅拷贝）


def test_score_market_relevance_optional_and_degrade_safe():
    mkts = _rel_markets()
    assert score_market_relevance(None, "q", mkts) == mkts                 # llm_call=None → 跳过
    assert score_market_relevance(None, "q", None) == []                   # 空输入 → []

    def boom(prompt):
        raise RuntimeError("llm down")

    assert score_market_relevance(boom, "q", mkts) == mkts                 # 异常 → 原样（volume 排序不变）
    assert score_market_relevance(lambda p: "no json", "q", mkts) == mkts  # 不可解析 → 原样
    assert score_market_relevance(lambda p: "[]", "q", mkts) == mkts       # 空打分 → 原样


def test_score_market_relevance_unscored_rows_kept():
    def llm(prompt):
        return json.dumps([{"market_id": "m1", "score": 1}])  # 只覆盖 m1

    out = score_market_relevance(llm, "q", _rel_markets(), min_relevance=5)
    # m1 低分剔除；m2/m3 未被覆盖 → 保留（不因缺分丢信号），同视作门槛分后按 volume 排序
    assert [m["market_id"] for m in out] == ["m3", "m2"]
    assert all("relevance_score" not in m for m in out)


def test_snapshot_applies_relevance_gate_when_llm_call_given(enabled, monkeypatch):
    payload = _payload([_event("Big", [_raw("m-big", vol=9000, yes="0.6400"),
                                       _raw("m-small", vol=500, yes="0.2100")])])
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: FakeResponse(payload))

    def llm(prompt):
        return json.dumps([{"market_id": "m-big", "score": 2, "rationale": "unrelated"},
                           {"market_id": "m-small", "score": 8, "rationale": "on point"}])

    out = PolymarketClient().snapshot_for_queries(["x"], llm_call=llm, question="research q")
    assert [m["market_id"] for m in out] == ["m-small"]      # 高量但不相关的 m-big 被剔除
    assert out[0]["relevance_score"] == 8.0
    # llm_call 未提供 → 今天的行为：volume-only 排序、无打分字段
    out2 = PolymarketClient().snapshot_for_queries(["x"])
    assert [m["market_id"] for m in out2] == ["m-big", "m-small"]
    assert all("relevance_score" not in m for m in out2)


# ------------------------------------------------------------- rendering

def test_render_markets_block_deterministic_table():
    markets = [
        {"market_id": "m1", "exchange": "polymarket", "question": "Will tariffs exceed 10%?",
         "implied_yes_prob": 0.64, "volume": 9000, "liquidity": 50,
         "event_title": "Tariffs", "matched_query": "tariff"},
        {"market_id": "m2", "exchange": "polymarket", "question": "Fed cuts | twice?",
         "implied_yes_prob": 0.21, "volume": 500, "liquidity": 10,
         "event_title": "Fed", "matched_query": "Fed rate"},
    ]
    block = render_markets_block(markets, lang="en")
    assert "Prediction Market Signals (Polymarket)" in block
    assert "| 1 | Will tariffs exceed 10%? (m1) | polymarket | 64% | 9,000 |" in block
    assert "Fed cuts ／ twice?" in block             # 管道符转义
    assert "calibration anchors, not ground truth" in block  # 时效/非真值告示
    # 中文渲染 + 空列表降级
    zh = render_markets_block(markets, lang="zh")
    assert "隐含 P(yes)" in zh and "校准锚点" in zh
    assert render_markets_block([]) == ""
    assert render_markets_block(None) == ""


# ------------------------------------------------------- query derivation

def test_derive_market_queries_heuristic():
    q = derive_market_queries(
        "Will the US semiconductor export controls tighten before 2027?",
        hot_topics=["tariff escalation", "AI capex boom cycle expansion and more"],
        actor_names=["Federal Reserve", "NVIDIA"],
    )
    assert q  # 非空
    assert all(len(x.split()) <= 5 for x in q)       # 每条 ≤5 词
    assert len(q) <= 12                              # 限量（6→12 放宽）
    assert len({x.lower() for x in q}) == len(q)     # 去重
    joined = " || ".join(q)
    assert "semiconductor" in joined                 # 问题关键短语被抽出
    assert "the" not in [w.lower() for x in q for w in x.split()]  # 停用词被滤掉
    assert "tariff escalation" in q                  # hot_topics 直通
    assert "AI capex boom cycle expansion" in q      # 超长 topic 截到 5 词
    assert "Federal Reserve" in q and "NVIDIA" in q  # actor 名直通


def test_derive_market_queries_dedupes_and_handles_empty():
    assert derive_market_queries("") == []
    q = derive_market_queries("tariff tariff tariff", hot_topics=["Tariff"])
    assert [x.lower() for x in q].count("tariff") == 1  # 大小写不敏感去重


def test_derive_market_queries_cjk_question():
    q = derive_market_queries("美联储会在2026年降息吗？关税战是否升级？")
    assert q  # CJK 串作为整体 token 被抽出
    assert any("关税" in x or "美联储" in x for x in q)


def test_derive_market_queries_keeps_four_digit_years():
    q = derive_market_queries("Will a US recession start in 2026?")
    assert any("2026" in x for x in q)               # 年份 token 不再被 regex 丢弃
    assert "recession start" in " || ".join(q)


def test_derive_market_queries_blacklists_generic_words():
    q = derive_market_queries("Key factors impact the outcome of tariff policy escalation")
    words = {w.lower() for x in q for w in x.split()}
    assert not words & {"key", "factors", "impact", "outcome", "cover"}  # 泛化空词被滤掉
    assert "tariff policy escalation" in q           # 实义短语完整保留


def test_salient_phrases_break_at_clause_boundaries():
    # 短语不得跨逗号拼出无意义组合（"rise china"）；两个子句各自成短语。
    assert pm._salient_phrases("tariffs rise, china retaliates") == \
        ["tariffs rise", "china retaliates"]


def test_derive_market_queries_reserves_slots_for_actors():
    q = derive_market_queries(
        "alpha beta, gamma delta, epsilon zeta",
        hot_topics=["topic one", "topic two", "topic three"],
        actor_names=["Federal Reserve", "NVIDIA"],
        max_queries=4,
    )
    assert len(q) == 4
    assert "Federal Reserve" in q and "NVIDIA" in q  # 短语/话题填满也挤不掉 actor 名


# --------------------------------------------- LLM query derivation

def test_derive_market_queries_llm_happy_path():
    titles = [f"Fed rate cut {2026 + i}" for i in range(12)]
    prompts = []

    def llm(prompt):
        prompts.append(prompt)
        return "Sure, here you go:\n```json\n" + json.dumps(titles) + "\n```"

    q = derive_market_queries_llm(llm, "Will the Fed cut rates?",
                                  hot_topics=["inflation"], actors=["Federal Reserve"])
    assert q == titles                               # 代码栅栏 + 散文包裹被鲁棒解析
    assert 10 <= len(q) <= 16
    assert "Will the Fed cut rates?" in prompts[0]   # 问题/话题/actor 全部入 prompt
    assert "inflation" in prompts[0] and "Federal Reserve" in prompts[0]


def test_derive_market_queries_llm_wrapped_payload_dedup_and_topup():
    def llm(prompt):
        return json.dumps({"queries": [
            {"query": "US recession 2026"},          # dict 元素也接受
            "China Taiwan blockade",
            "US recession 2026",                     # 重复 → 去重
        ]})

    question = "Will the US semiconductor export controls tighten before 2027?"
    q = derive_market_queries_llm(llm, question, actors=["NVIDIA"])
    assert q[0] == "US recession 2026" and q[1] == "China Taiwan blockade"
    assert [x.lower() for x in q].count("us recession 2026") == 1
    assert "NVIDIA" in q                             # 产出不足 → 启发式确定性补足
    assert len({x.lower() for x in q}) == len(q)


def test_derive_market_queries_llm_falls_back_to_heuristic():
    question = "Will the US semiconductor export controls tighten before 2027?"
    heur = derive_market_queries(question, hot_topics=["tariff escalation"],
                                 actor_names=["NVIDIA"], max_queries=12)

    def boom(prompt):
        raise RuntimeError("llm down")

    for bad_call in (None, boom, lambda p: "no json here at all", lambda p: "[]"):
        assert derive_market_queries_llm(
            bad_call, question, hot_topics=["tariff escalation"],
            actors=["NVIDIA"]) == heur               # 任何失败 → 与启发式逐条一致


# --------------------------------------------- forecast_extractor plumbing

_MARKETS = [
    {"market_id": "mkt-1", "exchange": "polymarket", "question": "Tariffs > 10%?",
     "implied_yes_prob": 0.30, "volume": 9000, "liquidity": 50,
     "event_title": "Tariffs", "matched_query": "tariff"},
]
_MARKET_PACK = render_markets_block(_MARKETS, lang="en")


def test_binary_forecasts_market_anchor_plumbing(enabled):
    fake = FakeLLMClient(json_responses=[{
        "binary_forecasts": [
            {"id": "F1", "statement": "US effective tariff rate averages over 10% from 2026-2028",
             "probability": 0.25, "resolution_criteria": "USITC tariff data > 10% by 2028",
             "theme": "trade", "horizon_year": 2028,
             "market_anchor": {"market_id": "mkt-1", "implied_yes_prob": 0.99}},
            {"id": "F2", "statement": "AI capex exceeds $500B in 2027",
             "probability": 0.80, "resolution_criteria": "Aggregate hyperscaler capex > $500B in 2027",
             "theme": "ai", "horizon_year": 2027,
             "market_anchor": {"implied_yes_prob": 0.5}},   # 缺 market_id → 锚点被丢弃
        ],
    }])
    out = extract_binary_forecasts(
        "dossier text", fake, min_count=2, language="English",
        market_pack=_MARKET_PACK, markets=_MARKETS)
    binaries = out["binary_forecasts"]
    assert len(binaries) == 2
    f1 = next(b for b in binaries if "tariff" in b["statement"])
    # 隐含概率以我们的快照价（0.30）为准，不盲信模型转录的 0.99；divergence 确定性计算。
    assert f1["market_anchor"] == {"market_id": "mkt-1", "implied_yes_prob": 0.30,
                                   "divergence": round(0.25 - 0.30, 4)}
    f2 = next(b for b in binaries if "capex" in b["statement"])
    assert "market_anchor" not in f2
    # 提示词包含市场校准指令 + 市场表
    prompt = fake.calls[0]["messages"][0]["content"]
    assert "MARKET CALIBRATION" in prompt
    assert "[Prediction market signals]" in prompt
    assert "mkt-1" in prompt


def test_binary_forecasts_without_market_pack_prompt_unchanged():
    fake = FakeLLMClient(json_responses=[{
        "binary_forecasts": [
            {"id": "F1", "statement": "S1", "probability": 0.25,
             "resolution_criteria": "metric > 1 by 2027", "theme": "t"},
            {"id": "F2", "statement": "S2", "probability": 0.80,
             "resolution_criteria": "metric > 2 by 2027", "theme": "t"},
        ],
    }])
    out = extract_binary_forecasts("dossier", fake, min_count=2, language="English")
    prompt = fake.calls[0]["messages"][0]["content"]
    assert "MARKET CALIBRATION" not in prompt
    assert "[Prediction market signals]" not in prompt
    assert all("market_anchor" not in b for b in out["binary_forecasts"])


def test_render_binary_block_market_column_only_when_anchored():
    anchored = {
        "binary_forecasts": [
            {"id": "F1", "statement": "Tariffs stay above 10%", "probability": 0.25,
             "resolution_criteria": "USITC > 10% by 2028", "theme": "trade",
             "market_anchor": {"market_id": "mkt-1", "implied_yes_prob": 0.30,
                               "divergence": -0.05}},
            {"id": "F2", "statement": "AI capex exceeds $500B", "probability": 0.80,
             "resolution_criteria": "capex > $500B in 2027", "theme": "ai"},
        ],
        "binary_quality": {"count": 2, "conviction_count": 2, "sharp_criteria_count": 2},
    }
    block = render_binary_forecasts_block(anchored, language="English")
    assert "Market P(yes)" in block                  # 有锚点 → 追加市场列
    assert "30% (Δ-5pt)" in block                    # 隐含概率 + 分歧（点数）
    assert block.count("| F2 |") == 1 and "| — |" in block  # 无锚点行显示占位符

    plain = {
        "binary_forecasts": [
            {"id": "F1", "statement": "S", "probability": 0.5,
             "resolution_criteria": "m > 1 by 2027", "theme": "t"},
        ],
    }
    assert "Market P(yes)" not in render_binary_forecasts_block(plain, language="English")

    zh = render_binary_forecasts_block(anchored, language="Chinese")
    assert "市场隐含 P(yes)" in zh                   # 中文列头随输出语言


def test_derive_forecast_spine_injects_market_block():
    scen = {
        "headline": "h", "horizon": "2027",
        "scenarios": [
            {"name": "A", "probability": 0.6, "summary": "s", "key_drivers": [],
             "resolution_criteria": "x > 1 by 2027"},
            {"name": "B", "probability": 0.4, "summary": "s", "key_drivers": [],
             "resolution_criteria": "x <= 1 by 2027"},
        ],
        "confidence": "medium",
    }
    fake = FakeLLMClient(json_responses=[dict(scen) for _ in range(6)])
    out = derive_forecast_spine(fake, central_question="q", market_block=_MARKET_PACK)
    assert out["scenarios"]
    prompt = fake.calls[0]["messages"][0]["content"]
    assert "预测市场隐含概率" in prompt and "mkt-1" in prompt
    assert "校准锚点" in prompt

    fake2 = FakeLLMClient(json_responses=[dict(scen) for _ in range(6)])
    derive_forecast_spine(fake2, central_question="q")
    assert "预测市场隐含概率" not in fake2.calls[0]["messages"][0]["content"]  # 空块 → 提示词不变
