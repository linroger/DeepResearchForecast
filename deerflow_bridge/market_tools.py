"""Bridge config-reflected tool: Polymarket 预测市场检索（官方公开 Gamma API，keyless）。

改编自 drf2/config/market_tools.py（同一批端点、过滤规则、degrade-safe 语义），部署为
deer-flow harness 的 `tools:` 条目入口——config.yaml 里 `use: market_tools:
prediction_market_search_tool`。deerflow_research.py 以 ``python <deer-flow>/
deerflow_research.py`` 启动（pipeline_orchestrator cwd=deer-flow/），``sys.path[0]``
即脚本目录，本模块与 config.yaml 一起同步到该目录后即可被 harness 的 reflection
(`resolve_variable`) 以裸模块名导入。约束：

* **自包含**：只用 stdlib + requests（deer-flow venv 自带 requests，且延迟导入 +
  ImportError 兜底），不 import backend/app、不 import deerflow.*。数据源是
  Polymarket 官方公开 Gamma API——检索/浏览公开市场无需 API key、无需钱包。
* **degrade-safe**：网络失败 / 解析失败 / requests 缺失一律返回带说明的空结果字符串，
  绝不向 harness 抛异常、绝不阻断研究主流程。
* **langchain 可选**：harness 环境必有 langchain_core，模块底部把纯函数包成 BaseTool；
  无 langchain 的环境（离线单测纯逻辑）import 本模块仍成功，该变量为 None。
* **env 旋钮沿用既有名字**（与 deerflow_research.py 落盘阶段同一组，缺省即今日行为）：
  PREDICTION_MARKETS_MIN_VOLUME（默认 200）、PREDICTION_MARKETS_MAX（默认 20）、
  PREDICTION_MARKETS_MAX_PER_EVENT（默认 3）、PREDICTION_MARKETS_PER_QUERY（默认 8）。
  非法值回落默认。
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

POLYMARKET_BASE_URL = "https://gamma-api.polymarket.com"

# 可重试的瞬时错误状态码（限流/网关抖动）；4xx 参数错误不重试。
_TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})
# 唯一一次重试前的等待上限（秒）：数值型 Retry-After 被夹到 [0, 此值]；无/非数值头则
# 0.5–1.5s 抖动。零等待立即重试几乎必然再次 429，白白用掉唯一的重试机会。
_RETRY_AFTER_CAP_S = 10.0

# 过滤阈值缺省（与 legacy prediction_markets.snapshot_for_queries / drf2 版一致）
DEFAULT_MIN_VOLUME = 200.0
DEFAULT_PER_QUERY = 8
DEFAULT_MAX_TOTAL = 20
DEFAULT_MAX_PER_EVENT = 3
DEFAULT_TIMEOUT = 15.0
DEFAULT_NEGATIVE_CACHE_TTL_SECONDS = 30.0
DEFAULT_SINGLEFLIGHT_WAIT_SECONDS = 35.0

# A market discovered inside an agent turn used to exist only in that turn's
# chat transcript.  The later deterministic refresh could choose different
# queries (or return no matches), which meant a market the researcher actually
# used never reached the canonical handoff.  When the bridge supplies a run
# artifact directory, retain every machine-fetched candidate set as append-only
# JSONL.  The bridge performs the final relevance gate and compaction; this tool
# only records provenance.  The lock protects concurrent DeerFlow subagents in
# the same process and each record is emitted with one write.
MARKET_CANDIDATES_FILENAME = "prediction_market_candidates.jsonl"
_CAPTURE_LOCK = threading.Lock()
_QUERY_CACHE_LOCK = threading.Lock()
_QUERY_CACHE: "OrderedDict[tuple, Dict[str, Any]]" = OrderedDict()
_QUERY_INFLIGHT: Dict[tuple, Dict[str, Any]] = {}
_QUERY_CACHE_MAX = 128


class _MarketTransportFailure(RuntimeError):
    """Internal marker for a query whose provider response was not obtained."""


def _env_float(name: str, default: float) -> float:
    """读浮点 env 旋钮；缺省/非法值回落 default（degrade-safe）。"""
    try:
        raw = os.environ.get(name, "").strip()
        return float(raw) if raw else float(default)
    except (TypeError, ValueError):
        return float(default)


def _env_int(name: str, default: int) -> int:
    """读整型 env 旋钮；缺省/非法值回落 default（degrade-safe）。"""
    try:
        raw = os.environ.get(name, "").strip()
        return int(raw) if raw else int(default)
    except (TypeError, ValueError):
        return int(default)


def _bounded_env_seconds(name: str, default: float, maximum: float) -> float:
    """Read an operator duration knob without permitting infinite waits/TTLs."""
    value = _env_float(name, default)
    if not math.isfinite(value):
        value = float(default)
    return min(max(0.0, value), float(maximum))


def _coerce_float(v: Any) -> Optional[float]:
    """把 API 的字符串数值（如 volume="32970.32"）安全转成 float；失败返回 None。"""
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _as_list(v: Any) -> List[Any]:
    """Polymarket 的 outcomes/outcomePrices 常是 JSON 串（'["Yes","No"]'）也可能已是 list。"""
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []
    return []


def _yes_price(outcomes: Any, prices: Any) -> Optional[float]:
    """从 outcomes/outcomePrices 取 "Yes" 对应的隐含概率；无法定位则 None。"""
    names = _as_list(outcomes)
    px = _as_list(prices)
    if not names or not px or len(names) != len(px):
        return None
    for i, name in enumerate(names):
        if str(name).strip().lower() == "yes":
            return _coerce_float(px[i])
    return None


def _market_url(event_slug: str, market_slug: str) -> str:
    """拼公开市场页 URL：优先事件页（一个事件聚合其全部子市场），退回市场页；都无则空串。"""
    if event_slug:
        return f"https://polymarket.com/event/{event_slug}"
    if market_slug:
        return f"https://polymarket.com/market/{market_slug}"
    return ""


def _retry_wait(resp: Any) -> float:
    """瞬时状态重试前的等待秒数：有限数值型 Retry-After 夹到 [0, 10]，否则 U(0.5, 1.5) 抖动。"""
    try:
        raw = (getattr(resp, "headers", None) or {}).get("Retry-After")
        seconds = float(str(raw).strip()) if raw is not None else math.nan
    except (AttributeError, TypeError, ValueError):
        seconds = math.nan
    if math.isfinite(seconds):
        return min(max(seconds, 0.0), _RETRY_AFTER_CAP_S)
    return random.uniform(0.5, 1.5)


def _http_get(path: str, params: Dict[str, Any], timeout: float = DEFAULT_TIMEOUT) -> Any:
    """GET 一个 Polymarket 端点并解析 JSON（keyless）。瞬时错误重试一次；任何失败返回 None（绝不上抛）。"""
    try:
        import requests
    except ImportError:  # noqa: BLE001 — 环境无 requests → 空结果，不阻断
        logger.warning("prediction_market_search: requests 不可用，降级为空结果")
        return None
    url = POLYMARKET_BASE_URL + path
    last_err: Any = None
    for attempt in (1, 2):
        try:
            resp = requests.get(url, params=params, timeout=timeout,
                                headers={"Accept": "application/json"})
            if resp.status_code in _TRANSIENT_STATUS and attempt == 1:
                last_err = f"HTTP {resp.status_code}"
                time.sleep(_retry_wait(resp))
                continue
            resp.raise_for_status()
            return resp.json()
        except (requests.ConnectionError, requests.Timeout) as e:  # 连接/超时类瞬时错误 → 重试一次
            last_err = e
            continue
        except Exception as e:  # noqa: BLE001 — 4xx/JSON 解析等非瞬时错误不重试
            last_err = e
            break
    logger.warning(f"Polymarket GET {path} 失败（降级为空结果）: {last_err}")
    return None


def normalize_market(raw: Any, matched_query: str,
                     min_volume: float = DEFAULT_MIN_VOLUME,
                     event_title: str = "",
                     event_slug: str = "") -> Optional[Dict[str, Any]]:
    """单条 Polymarket 市场规整化；不合格（已关闭/无价/定盘价/低量）返回 None。

    规则与 deerflow_research.py 落盘阶段 / legacy PolymarketClient._normalize_market
    逐条一致——市场只有在未关闭、价格严格落在 (0,1)、volume>=min_volume 时才配当校准
    锚点。额外带上 url + end_date，供 skill 的 "Prediction Market Signals" 表引用。
    """
    if not isinstance(raw, dict):
        return None
    market_id = str(raw.get("id") or "").strip()
    question = str(raw.get("question") or "").strip()
    if not market_id or not question:
        return None
    # 已关闭/已判定 → 不配当锚点（active 旗标在已判定市场上仍为 True，不可靠）。
    if raw.get("closed") is True or str(raw.get("closed")).strip().lower() == "true":
        return None
    prob = _yes_price(raw.get("outcomes"), raw.get("outcomePrices"))
    # 价格须严格落在 (0,1)：恰为 0/1 = 市场实质已定盘，作为校准锚点没有意义。
    if prob is None or not (0.0 < prob < 1.0):
        return None
    volume = _coerce_float(raw.get("volume")) or 0.0
    liquidity = _coerce_float(raw.get("liquidity")) or 0.0
    if volume < float(min_volume):
        return None  # 极低量的价格是噪声，不配当锚点
    record: Dict[str, Any] = {
        "market_id": market_id,
        "exchange": "polymarket",
        "question": question,
        "implied_yes_prob": round(prob, 4),
        "volume": volume,
        "liquidity": liquidity,
        "event_title": event_title or str(raw.get("groupItemTitle") or "").strip(),
        "matched_query": matched_query,
        "url": _market_url(event_slug, str(raw.get("slug") or "").strip()),
        "end_date": str(raw.get("endDate") or "").strip(),
    }
    # LOOP-017 P1：工具选中的市场必须带下游（历史价时间线 _pm_fetch_price_history /
    # 重报价核对）所需的 CLOB/结局字段——candidates.jsonl → registry 合并按整行 dict
    # 透传，字段在此处缺了就永远缺了（历史事故：只被工具发现、未被确定性刷新重召回的
    # 市场画不出历史价）。clobTokenIds 与 outcomes **位置对齐**（Gamma 契约），市场偶有
    # ["No","Yes"] 排序：额外给显式的 clob_yes_token_id（按 "Yes" 下标定位，绝非下标 0；
    # 下标超出 token 范围时不造假）。全部 additive、缺失不造假（键不出现）。
    outcome_names = [str(n).strip() for n in _as_list(raw.get("outcomes"))]
    if outcome_names:
        record["outcomes"] = outcome_names
    outcome_prices = [_coerce_float(p) for p in _as_list(raw.get("outcomePrices"))]
    if outcome_prices and all(p is not None for p in outcome_prices):
        record["outcome_prices"] = [round(float(p), 4) for p in outcome_prices]
    clob_ids = [str(t).strip() for t in _as_list(raw.get("clobTokenIds")) if str(t).strip()]
    if clob_ids:
        record["clob_token_ids"] = clob_ids
        yes_idx = next((i for i, n in enumerate(outcome_names)
                        if n.lower() == "yes"), None)
        if yes_idx is not None and yes_idx < len(clob_ids):
            record["clob_yes_token_id"] = clob_ids[yes_idx]
    return record


def _cap_per_event(ranked: List[Dict[str, Any]], max_per_event: int,
                   max_total: int) -> List[Dict[str, Any]]:
    """在已按 volume 降序的市场列表上，限制每个事件最多 max_per_event 条，再截到 max_total。
    保证多事件多样性（一个多结局事件的子市场阶梯不霸占全部名额）。<=0 视为不限制。"""
    if int(max_per_event) <= 0:
        return ranked[:max(0, int(max_total))]
    per_event: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []
    for m in ranked:
        key = str(m.get("event_title") or "").strip() or m.get("market_id") or ""
        n = per_event.get(key, 0)
        if n >= int(max_per_event):
            continue
        per_event[key] = n + 1
        out.append(m)
    return out[:max(0, int(max_total))]


def snapshot_for_queries(queries: List[str],
                         per_query: int = DEFAULT_PER_QUERY,
                         max_total: int = DEFAULT_MAX_TOTAL,
                         min_volume: float = DEFAULT_MIN_VOLUME,
                         max_per_event: int = DEFAULT_MAX_PER_EVENT,
                         fetch: Any = None,
                         diagnostics: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """对一组检索词取活跃市场快照并规整化（按 market_id 去重，volume 降序，每事件≤max_per_event，限量）。

    ``fetch(query, limit) -> list[event]`` 可注入（单测 mock 网络）；缺省走 Polymarket
    /public-search（每个事件下挂多个市场，展开后规整）。Degrade-safe：任一 query 失败
    只丢那一批，整体绝不抛。
    """
    def _default_fetch(q: str, limit: int) -> List[Any]:
        data = _http_get("/public-search", {"q": q, "limit_per_type": limit,
                                            "events_status": "active"})
        if data is None:
            raise _MarketTransportFailure("Polymarket public-search unavailable")
        if not isinstance(data, dict) or not isinstance(data.get("events"), list):
            raise _MarketTransportFailure(
                "Polymarket public-search returned an invalid response schema"
            )
        return data["events"]

    fetch_fn = fetch if fetch is not None else _default_fetch

    by_id: Dict[str, Dict[str, Any]] = {}
    attempted = 0
    successful = 0
    transport_failures = 0
    raw_candidate_count = 0
    for q in queries or []:
        q = str(q or "").strip()
        if not q:
            continue
        attempted += 1
        try:
            events = fetch_fn(q, per_query)
        except Exception as e:  # noqa: BLE001 — 单个 query 失败不阻断整体
            transport_failures += 1
            logger.warning(f"prediction_market_search: query {q!r} 失败（跳过）: {e}")
            continue
        successful += 1
        for event in events or []:
            if not isinstance(event, dict):
                continue
            event_title = str(event.get("title") or "").strip()
            event_slug = str(event.get("slug") or "").strip()
            for raw in event.get("markets") or []:
                if isinstance(raw, dict):
                    raw_candidate_count += 1
                norm = normalize_market(raw, matched_query=q, min_volume=min_volume,
                                        event_title=event_title, event_slug=event_slug)
                if norm is None:
                    continue
                if norm["market_id"] not in by_id:
                    by_id[norm["market_id"]] = norm
    ranked = sorted(by_id.values(), key=lambda m: -(m.get("volume") or 0.0))
    if diagnostics is not None:
        diagnostics.update({
            "attempted_query_count": attempted,
            "successful_query_count": successful,
            "transport_failure_count": transport_failures,
            "raw_candidate_count": raw_candidate_count,
            "candidate_count": len(ranked),
        })
    return _cap_per_event(ranked, max_per_event, max_total)


def _capture_market_candidates(queries: List[str], markets: List[Dict[str, Any]],
                               status: Optional[Dict[str, Any]] = None) -> None:
    """Persist one tool result for the run-level market registry, best effort.

    ``DEERFLOW_RUN_ARTIFACT_DIR`` is set by the trusted parent process.  When it
    is absent (interactive/standalone use), malformed, or not an existing
    directory, capture is a no-op.  Capture failures never affect the tool
    response or the research run.
    """
    if not any(isinstance(row, dict) for row in (markets or [])):
        return
    root = str(os.environ.get("DEERFLOW_RUN_ARTIFACT_DIR") or "").strip()
    if not root:
        return
    try:
        resolved_root = os.path.realpath(root)
        if not os.path.isdir(resolved_root):
            return
        path = os.path.realpath(os.path.join(resolved_root, MARKET_CANDIDATES_FILENAME))
        if os.path.commonpath([resolved_root, path]) != resolved_root:
            return
        record = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "source": "polymarket",
            "queries": [str(q) for q in (queries or []) if str(q).strip()],
            "markets": [m for m in (markets or []) if isinstance(m, dict)],
        }
        if isinstance(status, dict):
            record["status"] = dict(status)
        encoded = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        # One pathological provider response must not turn this provenance log
        # into an unbounded artifact.  Normal tool results are tens of KB.
        if len(encoded) > 1_000_000:
            logger.warning("prediction market candidate capture skipped: record exceeds 1 MB")
            return
        with _CAPTURE_LOCK:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                view = memoryview(encoded)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError("short write while appending prediction-market ledger")
                    view = view[written:]
            finally:
                os.close(fd)
    except Exception as exc:  # noqa: BLE001 — provenance capture is never fatal
        logger.warning("prediction market candidate capture failed (non-fatal): %s", exc)


def _reset_market_query_cache() -> None:
    """Clear the process-local query cache (tests and explicit lifecycle resets)."""
    with _QUERY_CACHE_LOCK:
        _QUERY_CACHE.clear()
        for flight in _QUERY_INFLIGHT.values():
            event = flight.get("event")
            if isinstance(event, threading.Event):
                event.set()
        _QUERY_INFLIGHT.clear()


def _cached_snapshot(queries: List[str], *, per_query: int, max_total: int,
                     min_volume: float, max_per_event: int
                     ) -> tuple[List[Dict[str, Any]], bool, bool, Dict[str, Any]]:
    """Track-local single-flight cache with explicit provider outcome semantics.

    Successful positive responses remain in the bounded process-local LRU.
    Verified empty responses have a finite TTL.  Any transport degradation or
    waiter timeout is never cached, so a transient outage cannot become a
    durable false assertion that no relevant market exists.
    """
    key = (
        tuple(sorted(str(q).strip().casefold() for q in queries)),
        int(per_query), int(max_total), float(min_volume), int(max_per_event),
    )
    owner = False
    now = time.monotonic()
    with _QUERY_CACHE_LOCK:
        cached = _QUERY_CACHE.get(key)
        if cached is not None:
            expires_at = cached.get("expires_at")
            if isinstance(expires_at, (int, float)) and now >= float(expires_at):
                _QUERY_CACHE.pop(key, None)
                cached = None
        if cached is not None:
            _QUERY_CACHE.move_to_end(key)
            return (
                [dict(row) for row in cached.get("markets") or []],
                True,
                False,
                dict(cached.get("status") or {}),
            )
        flight = _QUERY_INFLIGHT.get(key)
        if flight is None:
            flight = {"event": threading.Event(), "result": None}
            _QUERY_INFLIGHT[key] = flight
            owner = True

    if not owner:
        # Wait for the owner instead of multiplying an identical request.  A
        # timed-out waiter reports an unknown/in-flight outcome, never a cache
        # hit and never a verified empty market search.
        wait_seconds = _bounded_env_seconds(
            "PREDICTION_MARKETS_SINGLEFLIGHT_WAIT_SECONDS",
            DEFAULT_SINGLEFLIGHT_WAIT_SECONDS,
            120.0,
        )
        completed = flight["event"].wait(timeout=wait_seconds)
        result = flight.get("result")
        if completed and isinstance(result, tuple) and len(result) == 2:
            shared_markets, shared_status = result
            return (
                [dict(row) for row in shared_markets],
                False,
                True,
                dict(shared_status),
            )
        return [], False, True, {
            "state": "inflight_timeout",
            "attempted": True,
            "attempted_query_count": len(queries),
            "query_count": len(queries),
            "successful_query_count": 0,
            "transport_failure_count": 0,
            "inflight_timeout_count": len(queries),
            "raw_candidate_count": 0,
            "candidate_count": 0,
            "empty_reason": "inflight_timeout",
        }

    markets: List[Dict[str, Any]] = []
    diagnostics: Dict[str, int] = {}
    status: Dict[str, Any]
    try:
        markets = snapshot_for_queries(
            queries,
            per_query=per_query,
            max_total=max_total,
            min_volume=min_volume,
            max_per_event=max_per_event,
            diagnostics=diagnostics,
        )
        attempted = max(0, int(diagnostics.get("attempted_query_count", len(queries))))
        successful = max(0, int(diagnostics.get("successful_query_count", attempted)))
        failures = max(0, int(diagnostics.get("transport_failure_count", 0)))
        raw_candidates = max(0, int(diagnostics.get("raw_candidate_count", len(markets))))
        candidate_count = max(0, int(diagnostics.get("candidate_count", len(markets))))
        all_failed = attempted > 0 and successful == 0 and failures >= attempted
        partial_failure = failures > 0 and not all_failed
        if all_failed:
            state = "transport_failure"
            empty_reason = "transport_failure"
        elif partial_failure:
            state = "partial_success" if markets else "partial_transport_failure"
            empty_reason = None if markets else "partial_transport_failure"
        elif markets:
            state = "success"
            empty_reason = None
        else:
            state = "verified_empty"
            empty_reason = "no_equivalent_market"
        status = {
            "state": state,
            "attempted": True,
            "attempted_query_count": attempted,
            "query_count": attempted,
            "successful_query_count": successful,
            "transport_failure_count": failures,
            "inflight_timeout_count": 0,
            "raw_candidate_count": raw_candidates,
            "candidate_count": candidate_count,
            "empty_reason": empty_reason,
        }
    except Exception as exc:  # noqa: BLE001 — retain structured outage diagnostics
        logger.warning("prediction_market_search snapshot failed (non-fatal): %s", exc)
        status = {
            "state": "transport_failure",
            "attempted": True,
            "attempted_query_count": len(queries),
            "query_count": len(queries),
            "successful_query_count": 0,
            "transport_failure_count": len(queries),
            "inflight_timeout_count": 0,
            "raw_candidate_count": 0,
            "candidate_count": 0,
            "empty_reason": "transport_failure",
        }
    finally:
        if owner:
            with _QUERY_CACHE_LOCK:
                cacheable = status.get("transport_failure_count", 0) == 0
                if cacheable:
                    expires_at = None
                    if not markets:
                        ttl = _bounded_env_seconds(
                            "PREDICTION_MARKETS_NEGATIVE_CACHE_TTL_SECONDS",
                            DEFAULT_NEGATIVE_CACHE_TTL_SECONDS,
                            3600.0,
                        )
                        expires_at = time.monotonic() + ttl
                    _QUERY_CACHE[key] = {
                        "markets": [dict(row) for row in markets],
                        "status": dict(status),
                        "expires_at": expires_at,
                    }
                    _QUERY_CACHE.move_to_end(key)
                    while len(_QUERY_CACHE) > _QUERY_CACHE_MAX:
                        _QUERY_CACHE.popitem(last=False)
                flight["result"] = ([dict(row) for row in markets], dict(status))
                _QUERY_INFLIGHT.pop(key, None)
                flight["event"].set()
    return [dict(row) for row in markets], False, False, status


def prediction_market_search_impl(queries: str) -> str:
    """纯逻辑入口：换行/逗号分隔的短检索词 → 市场快照 JSON 文本（LLM 可读）。

    阈值走既有 env 旋钮（PREDICTION_MARKETS_MIN_VOLUME / _MAX / _MAX_PER_EVENT），
    未设置时与今日落盘阶段的缺省逐一致。任何内部错误 → 带说明的空结果，绝不抛。
    """
    try:
        parts = [p.strip() for chunk in str(queries or "").splitlines()
                 for p in chunk.split(",")]
        qlist: List[str] = []
        seen_queries: set[str] = set()
        for part in parts:
            if not part:
                continue
            key = part.casefold()
            if key in seen_queries:
                continue
            seen_queries.add(key)
            qlist.append(part)
            if len(qlist) >= 6:
                break
        if not qlist:
            return json.dumps({
                "queries": [],
                "markets": [],
                "cache_hit": False,
                "singleflight_shared": False,
                "status": {
                    "state": "no_queries",
                    "attempted": False,
                    "attempted_query_count": 0,
                    "query_count": 0,
                    "successful_query_count": 0,
                    "transport_failure_count": 0,
                    "inflight_timeout_count": 0,
                    "raw_candidate_count": 0,
                    "candidate_count": 0,
                    "empty_reason": "no_queries",
                },
                "note": "no queries given",
            }, ensure_ascii=False)
        markets, cache_hit, singleflight_shared, status = _cached_snapshot(
            qlist,
            per_query=_env_int("PREDICTION_MARKETS_PER_QUERY", DEFAULT_PER_QUERY),
            max_total=_env_int("PREDICTION_MARKETS_MAX", DEFAULT_MAX_TOTAL),
            min_volume=_env_float("PREDICTION_MARKETS_MIN_VOLUME", DEFAULT_MIN_VOLUME),
            max_per_event=_env_int("PREDICTION_MARKETS_MAX_PER_EVENT", DEFAULT_MAX_PER_EVENT),
        )
        if not cache_hit and not singleflight_shared:
            _capture_market_candidates(qlist, markets, status)
        note = ("Machine-fetched snapshot of active Polymarket markets (public Gamma API, no key); "
                "prices move continuously. Market-implied probabilities are calibration "
                "anchors, not ground truth.")
        if not markets and status.get("state") == "verified_empty":
            note = "No active, liquid markets matched these queries. " + note
        elif not markets and status.get("state") == "transport_failure":
            note = "Prediction-market provider unavailable; no absence conclusion was reached."
        elif not markets and status.get("state") == "inflight_timeout":
            note = "An identical market query is still in flight; this caller timed out without a result."
        elif not markets and status.get("state") == "partial_transport_failure":
            note = "Prediction-market search was incomplete because some queries failed in transport."
        return json.dumps({"queries": qlist, "markets": markets, "cache_hit": cache_hit,
                           "singleflight_shared": singleflight_shared, "status": status,
                           "note": note},
                          ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001 — 工具层最后兜底：绝不向 agent 循环抛异常
        logger.warning(f"prediction_market_search: 意外失败（降级为空结果）: {e}")
        return json.dumps({
            "markets": [],
            "cache_hit": False,
            "singleflight_shared": False,
            "status": {
                "state": "transport_failure",
                "attempted": True,
                "attempted_query_count": 0,
                "query_count": 0,
                "successful_query_count": 0,
                "transport_failure_count": 1,
                "inflight_timeout_count": 0,
                "raw_candidate_count": 0,
                "candidate_count": 0,
                "empty_reason": "transport_failure",
            },
            "note": f"prediction market search unavailable: {e}",
        }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# harness 入口：langchain BaseTool（config.yaml `use:` 指向这个变量）。
# deer-flow venv 必有 langchain_core；无 langchain 的环境（离线跑纯逻辑单测）
# import 本模块仍需成功，故 langchain 缺失时该变量为 None。
# ---------------------------------------------------------------------------
try:
    from langchain_core.tools import tool as _lc_tool

    @_lc_tool("prediction_market_search")
    def prediction_market_search_tool(queries: str) -> str:
        """Search active prediction markets (Polymarket, public API — no key) for calibration anchors.

        Args:
            queries: Up to 6 SHORT search phrases (max ~5 words each), separated by
                newlines or commas — e.g. "tariff, semiconductor export, Fed rate cut".
                Full-text search works best with short salient phrases, not sentences.

        Returns:
            JSON with the filtered market snapshot: for each market its market_id,
            exchange, question, implied_yes_prob (last yes price), volume, liquidity,
            event_title, matched_query, url and end_date. Closed, unpriced, resolved
            (price 0/1), or low-volume markets are excluded. Inspect ``status.state``
            before interpreting an empty list: ``verified_empty`` is evidence of no
            liquid overlap, while transport/in-flight states are unknown outcomes.
            Never fabricate market prices.
        """
        return prediction_market_search_impl(queries)

except ImportError:  # noqa: BLE001 — 离线环境无 langchain：纯逻辑仍可测
    prediction_market_search_tool = None  # type: ignore[assignment]
