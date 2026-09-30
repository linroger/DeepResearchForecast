"""Polymarket 预测市场客户端（Gamma public-search，无需 API key）——市场隐含概率作为预测校准锚点。

深研管线在报告/预测阶段把「与研究问题相关的真实预测市场」的隐含概率注入提示词：
市场价格是持币者的聚合信念，是极好的**校准锚点**（calibration anchor）——但不是真值。
本模块保持依赖极轻（httpx + Config），全链路 degrade-safe：网络失败 / 解析失败 / 关闭旗标
一律记一条 warning 并返回空结果，绝不向调用方抛异常、绝不阻断主流程。

数据源（已验证，keyless）：Polymarket 官方公开 Gamma API——浏览/检索公开市场无需 API key、
无需钱包（`polymarket-cli` 亦仅是这套公开 API 的薄封装）。

    GET https://gamma-api.polymarket.com/public-search?q=<全文检索>&limit_per_type=N&events_status=active
      → {"events": [{"title", "slug", "markets": [{id, question, outcomes, outcomePrices,
                                                    volume, liquidity, closed, ...}], ...}], ...}

规整规则（隐含概率作为锚点的资格）：
  * `closed`（而非 `active`——已判定市场仍 active=True）是「是否可用作锚点」的可靠闸门；
  * `outcomes`/`outcomePrices` 是 JSON 串列表，隐含 P(yes) = "Yes" 对应下标的价格；
  * 价格必须严格落在 (0,1)——恰为 0/1 = 实质已定盘，作为锚点无意义；
  * 按 volume 过滤噪声（默认 ≥200），按 volume 降序去重限量。
"""

from __future__ import annotations

import json
import logging
import math
import random
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

from .point_in_time import parse_stamp_strict

logger = logging.getLogger(__name__)

POLYMARKET_BASE_URL = "https://gamma-api.polymarket.com"
# CLOB 官方公开端点（keyless）：某个 CLOB token 的历史价格序列，用于给锚点市场画时间线。
# 与 Gamma（gamma-api）不同宿主——重报价走 Gamma /markets，历史价走 clob /prices-history。
CLOB_BASE_URL = "https://clob.polymarket.com"

# 可重试的瞬时错误状态码（限流/网关抖动）；4xx 参数错误不重试。
_TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})

# TRANSPORT-DIAG: gamma-api 前面的 Cloudflare 会拦/降权默认的编程 UA（真实运行里
# stdlib "Python-urllib/3.x" 41/41 全灭、同日浏览器形 UA 正常的差分根因）；统一发
# 浏览器形 UA（与 deerflow_bridge/_polymarket_get 的 _POLYMARKET_UA 一致）。
_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _backoff_sleep(attempt: int) -> None:
    """瞬时错误（429/5xx/网络抖动）重试前的抖动退避（~0.5-1.0s）；单测 monkeypatch 成 no-op。"""
    time.sleep(min(2.0, 0.5 * attempt) + random.uniform(0.0, 0.5))

# MON-1 解析终态阈值：已判定市场的 outcomePrices 收敛到 ~0/1。某一结局价 ≥ HI 视作该
# 结局实现（胜出），另一结局对称落到 ≤ LO。留 0.99/0.01 的余量吸收浮点/微量残余流动性。
_RESOLVED_PRICE_HI = 0.99
_RESOLVED_PRICE_LO = 0.01


def _cfg(name: str, default: Any) -> Any:
    """读取 Config 旗标（degrade-safe；Config 不可导入/属性缺失时用默认值，绝不抛异常）。"""
    try:
        from ..config import Config
        return getattr(Config, name, default)
    except Exception:  # noqa: BLE001 — config 导入失败不得阻断市场信号（可选增强）
        return default


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
    """Polymarket 的 outcomes/outcomePrices 常是 JSON 串（'["Yes","No"]'）也可能已是 list；
    统一解析成 list，失败返回 []。"""
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []
    return []


def _extract_json_payload(text: Any) -> Any:
    """从 LLM 回复中鲁棒提取 JSON：容忍 markdown 代码栅栏与前后缀散文；失败返回 None。

    解析顺序：整段直接 json.loads → 剥 ``` 栅栏后再试 → 抓最外层平衡的 [] / {} 片段。
    绝不抛异常（degrade-safe——调用方在 None 时回退确定性启发式）。
    """
    s = str(text or "").strip()
    if not s:
        return None
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if fence:
        s = fence.group(1).strip()
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        pass
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start, end = s.find(open_ch), s.rfind(close_ch)
        if 0 <= start < end:
            try:
                return json.loads(s[start:end + 1])
            except (ValueError, TypeError):
                continue
    return None


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


def _fresh_yes_price(raw: Any) -> Optional[float]:
    """重报价用：从一条 Gamma /markets 行取当前 "Yes" 隐含概率，套用与规整化一致的锚点资格
    （已关闭 / 无可解析价 / 价格恰为 0/1 = 定盘 → 视作无效，返回 None）。不做成交量过滤——
    重报价对象是研究期已选中的市场，只关心价格新鲜度，不再重判噪声下限。"""
    if not isinstance(raw, dict):
        return None
    if raw.get("closed") is True or str(raw.get("closed")).strip().lower() == "true":
        return None  # 已关闭/已判定 → 不再是有效锚点
    prob = _yes_price(raw.get("outcomes"), raw.get("outcomePrices"))
    if prob is None or not (0.0 < prob < 1.0):
        return None
    return prob


# ------------------------------------------------------------ endDate hygiene
# TIME-3: a market whose endDate has passed can stay open (closed=false) at a near-settled
# price such as 0.03 while it awaits UMA resolution, and so passes every closed / 0-1 gate.
# Its price still informs evidence, but it must never anchor a binary forecast or seed SIM
# priors. Every comparison takes an injected ``now`` (market_clock_now() by default) so the
# checks are replayable and tests never depend on the wall clock.
_END_DATE_GRACE_MAX_HOURS = 168.0
_ISO_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_DATE_ONLY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[Zz]?$")


def market_clock_now() -> datetime:
    """Current UTC instant used for every endDate comparison and every requote ``quoted_at``
    stamp (the single test monkeypatch point)."""
    return datetime.now(timezone.utc)


def _as_utc(moment: datetime) -> datetime:
    """Aware UTC view of ``moment``; a naive datetime is read as UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def parse_market_end(value: Any) -> Optional[datetime]:
    """Parse a Polymarket endDate into an aware UTC datetime; anything unusable → None.

    This is the program's only endDate parser. Strings only (extended ``YYYY-MM-DD`` prefix):
      * a trailing ``Z`` means UTC; offsets and fractional seconds are accepted;
      * a date-only ``YYYY-MM-DD`` (a bare ``Z`` designator allowed) means the end of that
        UTC day (23:59:59.999999);
      * a naive timestamp is read as UTC; an aware one is converted to UTC.
    Never raises (bad calendar values, overflow and non-strings all return None).
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _ISO_DATE_PREFIX_RE.match(text):
        return None
    try:
        date_only = _DATE_ONLY_RE.match(text)
        if date_only:
            day = date.fromisoformat(date_only.group(1))
            return datetime(day.year, day.month, day.day, 23, 59, 59, 999999,
                            tzinfo=timezone.utc)
        if text[-1] in "Zz":
            text = text[:-1] + "+00:00"
        return _as_utc(datetime.fromisoformat(text))
    except (ValueError, OverflowError):
        return None


def _clamp_grace_hours(value: Any) -> float:
    """Grace hours as a finite float in [0, 168]; anything unusable → 0."""
    hours = _coerce_float(value)
    if hours is None or not math.isfinite(hours):
        return 0.0
    return max(0.0, min(_END_DATE_GRACE_MAX_HOURS, hours))


def _row_market_end(row: Any) -> Optional[datetime]:
    """Parsed end of a normalized market row (``end_date``, then raw ``endDate``)."""
    if not isinstance(row, dict):
        return None
    return parse_market_end(row.get("end_date") or row.get("endDate"))


def market_window_ended(row: Any, *, now: datetime, grace_hours: float = 0.0) -> bool:
    """True iff the row's end date plus the grace period lies before ``now``.

    Missing or unparseable end dates are tolerated (False): the gate only removes markets
    it can prove are past their resolution window. Never raises."""
    end = _row_market_end(row)
    if end is None or not isinstance(now, datetime):
        return False
    try:
        return end + timedelta(hours=_clamp_grace_hours(grace_hours)) < _as_utc(now)
    except OverflowError:
        return False


def end_date_gate_settings() -> Tuple[bool, float]:
    """(PREDICTION_MARKETS_END_DATE_GATE, grace hours clamped to [0, 168]) from Config."""
    return (bool(_cfg("PREDICTION_MARKETS_END_DATE_GATE", True)),
            _clamp_grace_hours(_cfg("PREDICTION_MARKETS_END_DATE_GRACE_HOURS", 0.0)))


def stamp_window_ended(rows: Any, *, now: datetime,
                       grace_hours: float = 0.0) -> Tuple[List[Dict[str, Any]], int]:
    """Shallow-copy the dict rows; rows whose window ended gain ``window_ended=True`` and
    ``window_ended_at`` (the parsed end, ISO UTC). Rows are never dropped. Returns the
    copies and how many were stamped."""
    out: List[Dict[str, Any]] = []
    stamped = 0
    for m in rows or []:
        if not isinstance(m, dict):
            continue
        m2 = dict(m)
        end = _row_market_end(m2)
        if end is not None and market_window_ended(m2, now=now, grace_hours=grace_hours):
            m2["window_ended"] = True
            m2["window_ended_at"] = end.isoformat()
            stamped += 1
        out.append(m2)
    return out, stamped


def exclude_window_ended(rows: Any, *, now: datetime,
                         grace_hours: float = 0.0) -> Tuple[List[Any], List[Dict[str, Any]]]:
    """Split rows into (eligible, excluded) for anchoring or SIM priors: a row is excluded
    when its window ended at ``now`` or it already carries a ``window_ended`` stamp (e.g.
    from the research snapshot). Both lists keep the input objects and their order."""
    kept: List[Any] = []
    excluded: List[Dict[str, Any]] = []
    for m in rows or []:
        if isinstance(m, dict) and (m.get("window_ended") is True
                                    or market_window_ended(m, now=now,
                                                           grace_hours=grace_hours)):
            excluded.append(m)
            continue
        kept.append(m)
    return kept, excluded


def drop_window_ended_rows(rows: Any) -> Tuple[List[Any], int]:
    """SIM-prior view of a market snapshot: under PREDICTION_MARKETS_END_DATE_GATE drop rows
    whose window ended at market_clock_now() (or already stamped) and return how many were
    dropped. Gate off → the rows unchanged and 0, so priors stay byte-identical."""
    gate, grace = end_date_gate_settings()
    if not gate:
        return list(rows or []), 0
    kept, excluded = exclude_window_ended(rows, now=market_clock_now(), grace_hours=grace)
    return kept, len(excluded)


# EVAL-6 (MARKET_ANCHOR_PRICE_TIME): when a row's implied_yes_prob was observed. A requote
# stamps ``quoted_at``; a research or report-time snapshot row carries ``snapshot_as_of``,
# which dates the price by the snapshot's as_of: an upper bound on when it was observed.
PRICE_TIME_BASIS_REQUOTE = "requote"
PRICE_TIME_BASIS_SNAPSHOT = "snapshot"


def price_time_enabled() -> bool:
    """MARKET_ANCHOR_PRICE_TIME from Config (default on)."""
    return bool(_cfg("MARKET_ANCHOR_PRICE_TIME", True))


def stamp_snapshot_as_of(rows: Any, as_of: Any) -> List[Dict[str, Any]]:
    """Shallow copies of the dict rows, each dated by the snapshot time ``as_of``.

    ``as_of`` is when the snapshot was written or fetched, an upper bound on when each row's
    price was observed (a research snapshot also holds agent-tool rows priced earlier in the
    run). A row that lacks ``snapshot_as_of`` gains ``as_of``; a row that already carries one
    keeps its own. A blank or non-string ``as_of`` stamps nothing. MARKET_ANCHOR_PRICE_TIME
    off → the dict rows themselves, untouched, so every artifact stays byte-identical.
    Never raises."""
    kept = [m for m in (rows or []) if isinstance(m, dict)]
    if not price_time_enabled() or not isinstance(as_of, str) or not as_of.strip():
        return kept
    out: List[Dict[str, Any]] = []
    for m in kept:
        m2 = dict(m)
        if not m2.get("snapshot_as_of"):
            m2["snapshot_as_of"] = as_of
        out.append(m2)
    return out


def market_price_time(row: Any) -> Optional[Tuple[str, str]]:
    """``(price_time, basis)`` dating a market row's implied_yes_prob, or None when unknown.

    ``quoted_at`` (stamped by requote_markets on a fresh price and kept through a later
    failed requote, whose retained price is still that quote) → basis 'requote'; otherwise
    ``snapshot_as_of`` (the research snapshot's as_of or the report-time fetch time) →
    basis 'snapshot'. A 'snapshot' time is an upper bound on when the price was observed,
    not the exact moment: the research bridge takes its as_of when it writes the snapshot,
    after merging agent-tool rows that may have been priced hours earlier, and rows carry
    no per-row observation time yet. Only a zone-aware ISO date-time counts
    (parse_stamp_strict, no bare dates) and it is returned exactly as stored. A row whose
    quoted_at is present but unusable is unknown, never 'snapshot': its price came from a
    requote, so the snapshot time would misdate it. Never raises."""
    if not isinstance(row, dict):
        return None
    quoted_at = row.get("quoted_at")
    if quoted_at is not None:
        if parse_stamp_strict(quoted_at, allow_date=False) is None:
            return None
        return quoted_at, PRICE_TIME_BASIS_REQUOTE
    snapshot_as_of = row.get("snapshot_as_of")
    if parse_stamp_strict(snapshot_as_of, allow_date=False) is None:
        return None
    return snapshot_as_of, PRICE_TIME_BASIS_SNAPSHOT


def _parse_resolution(raw: Any) -> Optional[Dict[str, Any]]:
    """MON-1：从一条 Gamma /markets 行防御式解析判定终态；不可判定 → resolved=False（unknown）。

    已判定市场：`closed=true` 且某一结局价收敛到 ~1（另一 ~0）。据此定胜出结局名与
    "Yes" 结局的最终价（二元真值）。任一字段缺失/形状异常都不抛，退化为 unknown。
    返回 None 仅当输入根本不是 dict（无 market_id 可键）。"""
    if not isinstance(raw, dict):
        return None
    market_id = str(raw.get("id") or "").strip()
    closed = raw.get("closed") is True or str(raw.get("closed")).strip().lower() == "true"
    # UMA 判定阶段（诊断透传）：不同 Gamma 版本键名略有差异，容忍单/复数两种拼写。
    uma_raw = raw.get("umaResolutionStatus")
    if uma_raw is None:
        uma_raw = raw.get("umaResolutionStatuses")
    if isinstance(uma_raw, (list, tuple)):
        # EVAL-2: a status history sent as a real JSON array keeps its JSON form (never a
        # Python repr), so current_uma_status can still read its last stage.
        uma_raw = json.dumps(list(uma_raw), ensure_ascii=False, default=str)
    uma_status = str(uma_raw).strip() if uma_raw not in (None, "") else None

    names = _as_list(raw.get("outcomes"))
    px = _as_list(raw.get("outcomePrices"))
    resolved_outcome: Optional[str] = None
    if names and px and len(names) == len(px):
        for i, name in enumerate(names):
            p = _coerce_float(px[i])
            if p is not None and p >= _RESOLVED_PRICE_HI:
                resolved_outcome = str(name).strip()
                break
    # "Yes" 结局的最终价（胜出=~1 / 落败=~0）——据此定二元真值；无法定位则 None。
    resolved_yes_price = _yes_price(raw.get("outcomes"), raw.get("outcomePrices"))
    # 判定成立：已关闭 且 能定位到一个价收敛到 ~1 的胜出结局。仅 uma/closed 但价未收敛 →
    # 仍视为 unknown（避免把「关闭但争议中/未定盘」误记为已判定）。
    resolved = bool(closed and resolved_outcome is not None)
    return {
        "market_id": market_id,
        "closed": closed,
        "resolved": resolved,
        "resolved_outcome": resolved_outcome,
        "resolved_yes_price": (round(resolved_yes_price, 4)
                               if resolved_yes_price is not None else None),
        "uma_status": uma_status,
        # EVAL-2 (additive): when the market closed, and whether it settled at all.
        "closed_time": _parse_closed_time(raw.get("closedTime")),
        "resolution_status": _resolution_status(closed, resolved, uma_status, px),
    }


# EVAL-2: a UMA-resolved market whose every outcome price sits at 0.5 ± this tolerance was
# settled 50/50 (Polymarket's "unknown / ambiguous" resolution): final, but not a YES or NO.
_AMBIGUOUS_PRICE_TOLERANCE = 0.01
_UMA_RESOLVED_RE = re.compile(r"\bresolved\b", re.IGNORECASE)


def _parse_closed_time(value: Any) -> Optional[str]:
    """Gamma ``closedTime`` as a UTC ISO string, or None.

    Only a date-time that names its zone is accepted (ISO with ``Z``/offset, or Gamma's
    ``'YYYY-MM-DD HH:MM:SS+00'``); a bare date or a naive time would be a guess about when
    the outcome became known. ``endDate`` is the scheduled end, never a known-at time, so it
    is never used as a fallback."""
    moment = parse_stamp_strict(value, allow_date=False)
    return moment.isoformat() if moment is not None else None


def current_uma_status(value: Any) -> str:
    """EVAL-2: the current UMA stage of a Gamma ``uma_status``, lower-cased ('' when absent).

    ``umaResolutionStatuses`` (the fallback key) is a stage history, a JSON-encoded
    list such as ``'["proposed","resolved"]'`` or a list; its LAST entry is the current
    stage, so an earlier proposal or dispute never keeps a resolved market pending. Any
    other value is a single stage and is returned as it is."""
    if isinstance(value, list):
        stages: List[Any] = value
    else:
        text = str(value if value is not None else "").strip()
        try:
            parsed = json.loads(text) if text.startswith("[") else None
        except ValueError:
            parsed = None
        if not isinstance(parsed, list):
            return text.lower()
        stages = parsed
    last = stages[-1] if stages else None
    return str(last).strip().lower() if last is not None else ""


def _resolution_status(closed: bool, resolved: bool, uma_status: Optional[str],
                       prices: List[Any]) -> str:
    """'settled' (a YES/NO outcome converged), 'ambiguous' (UMA-resolved 50/50) or 'unknown'."""
    if resolved:
        return "settled"
    if closed and _UMA_RESOLVED_RE.search(current_uma_status(uma_status)) and prices:
        values = [_coerce_float(p) for p in prices]
        if all(v is not None and abs(v - 0.5) <= _AMBIGUOUS_PRICE_TOLERANCE + 1e-9
               for v in values):
            return "ambiguous"
    return "unknown"


def _cap_per_event(ranked: List[Dict[str, Any]], max_per_event: int,
                   max_total: int) -> List[Dict[str, Any]]:
    """在已按 volume 降序的市场列表上，限制每个事件最多 max_per_event 条，再截到 max_total。

    保证多事件的多样性：一个多结局事件的子市场阶梯（如「N 次降息」0~12）不会靠高成交量
    霸占全部名额、把其他相关事件挤出。event_title 为空时以 market_id 兜底（视作独立事件）。
    max_per_event<=0 视为不限制。
    """
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


class PolymarketClient:
    """极薄的 Polymarket Gamma 客户端：10s 超时、瞬时错误抖动退避后重试一次、任何失败降级为空结果。

    无需 API key（公开 API）；仅 PREDICTION_MARKETS_ENABLED（默认开）时才发请求。
    TRANSPORT-DIAG：失败的错误类名/HTTP 状态 additive 记入 ``self.last_error``（最近一次失败的
    {error_class, http_status, url}）与 ``self.transport_errors``（"类名[:状态]" → 累计次数），
    供调用方持久化诊断——真实事故里只有失败计数、无错误类别，断网无从归因。
    """

    def __init__(self, base_url: str = POLYMARKET_BASE_URL, timeout: float = 10.0):
        self.base_url = str(base_url or POLYMARKET_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.last_error: Optional[Dict[str, Any]] = None
        self.transport_errors: Dict[str, int] = {}

    @property
    def enabled(self) -> bool:
        """PREDICTION_MARKETS_ENABLED（默认开）时启用。keyless——无需 key。"""
        return bool(_cfg("PREDICTION_MARKETS_ENABLED", True))

    # ------------------------------------------------------------------ HTTP
    def _request(self, url: str, params: Dict[str, Any]) -> Any:
        """GET 一个绝对 URL 并解析 JSON。瞬时错误（网络/超时/5xx/429）抖动退避后重试一次；
        其余失败记 warning 后返回 None（degrade-safe，绝不向上抛）。失败的错误类名/HTTP
        状态 additive 记入 self.last_error / self.transport_errors（供调用方持久化诊断）。
        Gamma 与 CLOB 两个宿主共用这套超时/重试/降级纪律。"""
        last_err: Any = None
        last_status: Optional[int] = None
        for attempt in (1, 2):
            try:
                resp = httpx.get(url, params=params, timeout=self.timeout,
                                 headers={"Accept": "application/json",
                                          "User-Agent": _BROWSER_UA})
                if resp.status_code in _TRANSIENT_STATUS and attempt == 1:
                    last_err = f"HTTP {resp.status_code}"
                    last_status = resp.status_code
                    _backoff_sleep(attempt)
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.TransportError as e:  # 连接/超时类瞬时错误 → 退避后重试一次
                last_err = e
                last_status = None
                if attempt == 1:
                    _backoff_sleep(attempt)
                continue
            except Exception as e:  # noqa: BLE001 — 4xx/JSON 解析等非瞬时错误不重试
                last_err = e
                _status = getattr(getattr(e, "response", None), "status_code", None)
                if _status is not None:
                    last_status = _status
                break
        # TRANSPORT-DIAG: 记录具体错误类名 + HTTP 状态（重试耗尽的瞬时状态码沿用 last_status）。
        error_class = ("HTTPStatusError" if isinstance(last_err, str)
                       else type(last_err).__name__ if last_err is not None else "UnknownError")
        label = f"{error_class}:{last_status}" if last_status is not None else error_class
        self.last_error = {"error_class": error_class, "http_status": last_status, "url": url}
        self.transport_errors[label] = self.transport_errors.get(label, 0) + 1
        logger.warning(f"Polymarket GET {url} 失败（降级为空结果；error_class={error_class}, "
                       f"http_status={last_status}）: {last_err}")
        return None

    def _get(self, path: str, params: Dict[str, Any]) -> Any:
        """相对 Gamma 端点（self.base_url + path）的 GET；复用 _request 的降级纪律。"""
        return self._request(self.base_url + path, params)

    # ------------------------------------------------------------- endpoints
    def search_events(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        """全文检索活跃事件（每个事件下挂多个市场）；失败/未启用返回 []。"""
        if not self.enabled or not str(query or "").strip():
            return []
        data = self._get("/public-search", {"q": str(query).strip(),
                                            "limit_per_type": limit,
                                            "events_status": "active"})
        if not isinstance(data, dict):
            return []
        events = data.get("events")
        return [e for e in events if isinstance(e, dict)] if isinstance(events, list) else []

    # -------------------------------------------------------------- snapshot
    def snapshot_for_queries(self, queries: List[str], per_query: Optional[int] = None,
                             max_total: int = 20, min_volume: float = 200,
                             max_per_event: int = 3, llm_call: Any = None,
                             question: str = "") -> List[Dict[str, Any]]:
        """对一组检索词取市场快照并规整化。

        规则：从每个匹配事件展开其市场，按 market_id 去重（首个命中的 query 记入
        matched_query）；剔除已关闭 / 无可解析价格 / 价格恰为 0/1 / 成交量低于
        min_volume 的市场；按 volume 降序，且**每个事件最多取 max_per_event 条**
        （避免一个多结局事件的子市场阶梯——如「N 次降息」0~12——霸占全部名额、把其他
        相关事件挤出），最后取前 max_total 条。输出统一 schema：
            {market_id, exchange, question, implied_yes_prob, volume, liquidity,
             event_title, matched_query [, url, end_date, one_day_price_change,
             best_bid, best_ask]}
        per_query 留空 = 读 PREDICTION_MARKETS_PER_QUERY（默认 15，每词的 limit_per_type）。
        可选 LLM 相关性门（llm_call+question 同时给出才生效）：对截断后的快照批量打分，
        剔除低相关市场并按 (relevance_score, volume) 重排；失败 → 保持 volume 排序。
        Degrade-safe：任一 query 失败只丢那一批，整体绝不抛。
        """
        if per_query is None:
            try:
                per_query = int(_cfg("PREDICTION_MARKETS_PER_QUERY", 15) or 15)
            except (TypeError, ValueError):
                per_query = 15
        by_id: Dict[str, Dict[str, Any]] = {}
        for q in queries or []:
            q = str(q or "").strip()
            if not q:
                continue
            for event in self.search_events(q, limit=per_query):
                event_title = str(event.get("title") or "").strip()
                event_slug = str(event.get("slug") or "").strip()
                for raw in event.get("markets") or []:
                    norm = self._normalize_market(raw, matched_query=q,
                                                  event_title=event_title,
                                                  min_volume=min_volume,
                                                  event_slug=event_slug)
                    if norm is None:
                        continue
                    if norm["market_id"] not in by_id:
                        by_id[norm["market_id"]] = norm
        ranked = sorted(by_id.values(), key=lambda m: -(m.get("volume") or 0.0))
        capped = _cap_per_event(ranked, max_per_event, max_total)
        # 可选相关性门：全文检索召回的市场常与题目只沾边（如搜 "Fed" 命中体育盘口）。
        # score_market_relevance 自带 degrade-safe——llm_call=None / 打分失败 → 原样返回。
        if llm_call is not None and str(question or "").strip():
            capped = score_market_relevance(llm_call, question, capped)
        return capped

    # -------------------------------------------------------------- requote
    def requote_markets(self, markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """对研究期已抓取的市场批量重报价：拉当前隐含概率，把研究期价与现价并陈。

        动机：报告成稿到用户读到之间市场会漂移；把研究期锚点（price_at_research）与
        当下价（新 implied_yes_prob）一起呈现，读者能一眼看到「34%→41%」这样的移动，
        判断锚点是否还成立。规则（对每行都返回，绝不丢行）：
          * price_at_research ← 原 implied_yes_prob（若已有 price_at_research 则沿用，幂等重入）；
          * implied_yes_prob  ← Gamma /markets 拉到的当前 "Yes" 价（覆盖旧值）；
          * price_delta       ← 现价 − 研究期价（有研究期价时才写）；
          * quoted_at         ← 本批取价时刻（UTC ISO，EVAL-6：仅 MARKET_ANCHOR_PRICE_TIME 开
            且拿到现价时写）；
          * 未知 / 已关闭 / 无可解析价 / 未启用 → 保留旧价并置 requote_failed=True（已有的
            quoted_at 原样保留：留下的旧价仍是那次报价，照旧由它定时）。
        批量走 Gamma `/markets?id=<id>&id=<id>...`（httpx 把 list 值编码为重复 id 参数），
        超过 chunk 大小时分批（PREDICTION_MARKETS_REQUOTE_CHUNK，默认 20）。
        Degrade-safe：任一批失败只丢那一批的新价（对应行标 requote_failed），整体绝不抛。
        """
        rows = [m for m in (markets or []) if isinstance(m, dict)]
        if not rows:
            return []
        # 收集待重报价的 market_id（去重保序）——未启用时跳过取数，各行走 requote_failed 分支。
        ids: List[str] = []
        seen_ids: set = set()
        for m in rows:
            mid = str(m.get("market_id") or "").strip()
            if mid and mid not in seen_ids:
                seen_ids.add(mid)
                ids.append(mid)
        fresh = self._fetch_fresh_markets(ids) if (self.enabled and ids) else {}
        # EVAL-6：整批一个取价时刻（现价到手之后取），只盖在拿到现价的行上。
        quoted_at = market_clock_now().isoformat() if price_time_enabled() else None
        out: List[Dict[str, Any]] = []
        for m in rows:
            m2 = dict(m)  # 浅拷贝：绝不原地污染调用方传入的行
            mid = str(m.get("market_id") or "").strip()
            # 研究期价：优先已有 price_at_research（幂等），否则取当前 implied_yes_prob。
            research = _coerce_float(m.get("price_at_research"))
            if research is None:
                research = _coerce_float(m.get("implied_yes_prob"))
            if research is not None:
                m2["price_at_research"] = round(research, 4)
            prob = _fresh_yes_price(fresh.get(mid)) if mid else None
            if prob is None:
                # 未知/已关闭/无价/未启用 → 保留旧价，标记失败，清掉可能残留的旧 delta。
                # 已有的 quoted_at 不动：它仍标定留下的旧价（EVAL-6）。
                m2["requote_failed"] = True
                m2.pop("price_delta", None)
            else:
                m2["implied_yes_prob"] = round(prob, 4)
                m2.pop("requote_failed", None)
                if quoted_at is not None:
                    m2["quoted_at"] = quoted_at
                if research is not None:
                    m2["price_delta"] = round(prob - research, 4)
                else:
                    m2.pop("price_delta", None)
            out.append(m2)
        return out

    def _fetch_fresh_markets(self, ids: List[str],
                             answered: Optional[Set[str]] = None) -> Dict[str, Dict[str, Any]]:
        """按 id 批量拉 Gamma /markets，返回 {market_id: raw_row}；任一批失败只丢那一批。

        Gamma `/markets` 支持重复 id 参数（?id=a&id=b）批量取；httpx 会把 {"id": [...]}
        编码为重复 key。响应通常是市场对象数组，也容忍 {"markets": [...]} / {"data": [...]} 包装。
        EVAL-2：传入 ``answered`` 时请求带显式 ``limit``（=本批 id 数，不吃 Gamma 的缺省页长），
        并把判定源确实应答过的 id 加进去（见 ``_confirm_answered``）；失败批次的 id 不在其中。
        """
        out: Dict[str, Dict[str, Any]] = {}
        try:
            chunk = int(_cfg("PREDICTION_MARKETS_REQUOTE_CHUNK", 20) or 20)
        except (TypeError, ValueError):
            chunk = 20
        if chunk <= 0:
            chunk = 20  # 分批大小非法 → 回落默认，避免 range 步长为 0 死循环
        for start in range(0, len(ids), chunk):
            batch = ids[start:start + chunk]
            params: Dict[str, Any] = {"id": batch}
            if answered is not None:
                params["limit"] = len(batch)
            data = self._get("/markets", params)
            if isinstance(data, list):
                raw_rows = data
            elif isinstance(data, dict):
                raw_rows = data.get("markets") or data.get("data") or []
            else:
                raw_rows = []
            for raw in raw_rows if isinstance(raw_rows, list) else []:
                if isinstance(raw, dict):
                    mid = str(raw.get("id") or "").strip()
                    if mid:
                        out[mid] = raw
            if answered is not None:
                answered.update(self._confirm_answered(batch, data, out))
        return out

    @staticmethod
    def _market_list(data: Any) -> Optional[List[Any]]:
        """Gamma /markets 响应里的市场行列表；响应不是市场列表（失败 / 形状异常）→ None。"""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("markets", "data"):
                if isinstance(data.get(key), list):
                    return data[key]
        return None

    def _confirm_answered(self, batch: List[str], data: Any,
                          out: Dict[str, Dict[str, Any]]) -> Set[str]:
        """EVAL-2：本批里判定源确实应答过的 id（返回了该行，或确认无此市场）。

        响应须是市场列表，且每行都是本批请求的 id（混进别的 id 说明 id 过滤没生效，
        缺行什么也证明不了）。多 id 批次里缺的行可能只是被截断：逐个单 id（limit=1）
        复查，单 id 请求应答且仍无该行才确认「无此市场」，复查拿到的行照常并入 ``out``。
        一次请求失败绝不确认任何缺行，以免把存在的市场永久 terminal。"""
        rows = self._market_list(data)
        if rows is None:
            return set()
        returned = {str(raw.get("id") or "").strip() for raw in rows if isinstance(raw, dict)}
        if not returned <= set(batch):
            return set()
        confirmed = set(returned)
        omitted = [mid for mid in batch if mid not in returned]
        if len(batch) == 1:
            return confirmed | set(omitted)
        for mid in omitted:
            single = self._market_list(self._get("/markets", {"id": [mid], "limit": 1}))
            if single is None:
                continue
            found = {str(raw.get("id") or "").strip(): raw
                     for raw in single if isinstance(raw, dict)}
            if not set(found) <= {mid}:
                continue
            if mid in found:
                out[mid] = found[mid]
            confirmed.add(mid)
        return confirmed

    # -------------------------------------------------------- price history
    def fetch_price_history(self, clob_token_id: str, interval: str = "1d",
                            days: int = 90) -> List[Dict[str, Any]]:
        """拉某个 CLOB token 的历史价格序列（keyless）；返回 [{t, p}] 或 [] （任何失败）。

        端点：GET https://clob.polymarket.com/prices-history?market=<clobTokenId>&interval=<interval>
        （interval 为回看窗口档位：1h/6h/1d/1w/1m/max）。响应形如 {"history": [{t, p}, ...]}。
        days>0 时对返回序列做时间裁剪，只保留最近 days 天的点（客户端裁剪，不额外发请求，
        与 interval 档位叠加取更严的一边）。t 转 int、p 转 float 并四舍五入；不可解析的点跳过。
        Degrade-safe：未启用 / 空 token / 网络或解析失败 → []（绝不抛）。
        """
        token = str(clob_token_id or "").strip()
        if not self.enabled or not token:
            return []
        params = {"market": token, "interval": str(interval or "1d").strip()}
        data = self._request(CLOB_BASE_URL + "/prices-history", params)
        if isinstance(data, dict):
            hist = data.get("history")
        elif isinstance(data, list):
            hist = data  # 少数形态直接是点数组
        else:
            hist = None
        if not isinstance(hist, list):
            return []
        # days>0 → 截断到最近 days 天（多数调用 interval 已收窄，这层是二次保险）。
        cutoff: Optional[float] = None
        try:
            d = int(days)
            if d > 0:
                cutoff = time.time() - d * 86400
        except (TypeError, ValueError):
            cutoff = None
        out: List[Dict[str, Any]] = []
        for pt in hist:
            if not isinstance(pt, dict):
                continue
            tf = _coerce_float(pt.get("t"))
            p = _coerce_float(pt.get("p"))
            if tf is None or p is None:
                continue  # 缺时间戳/价格的点是脏数据，跳过
            if cutoff is not None and tf < cutoff:
                continue
            out.append({"t": int(tf), "p": round(p, 4)})
        return out

    # --------------------------------------------------------- resolutions
    def fetch_resolutions(self, market_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """MON-1：查询一批市场的 closed/resolved 终态（keyless Gamma /markets）。

        动机：持续预测需要知道锚定市场何时**判定**——市场一旦 resolve，模型概率就有了
        真值标签，可回算 Brier。已判定市场的 outcomePrices 收敛到 ~0/1，`closed=true`，且
        Gamma 常带 `umaResolutionStatus`（UMA 预言机判定阶段）。本方法复用 `_fetch_fresh_markets`
        的批量取数与降级纪律，逐条防御式解析终态：

            {market_id: {market_id, closed, resolved, resolved_outcome,
                         resolved_yes_price, uma_status, closed_time, resolution_status}}

        * closed              —— 市场是否已关闭（active 旗标在已判定市场上仍 True，不可靠）；
        * resolved            —— 是否可判定为确定结局（closed 且某结局价 ≥ HI，收敛到 0/1）；
        * resolved_outcome    —— 胜出结局名（"Yes"/"No"/…），无法判定为 None；
        * resolved_yes_price  —— 判定后 "Yes" 结局的价（胜出=~1 / 落败=~0），据此定二元真值；
        * uma_status          —— 原样透传的 UMA 判定阶段字符串（诊断用；缺失为 None）；
        * closed_time         —— EVAL-2：Gamma closedTime 的 UTC ISO（须带时区；缺失/不可解析
                                 为 None，绝不以 endDate 代替）；
        * resolution_status   —— EVAL-2：'settled' / 'ambiguous'（UMA 判定 50/50）/ 'unknown'。

        Degrade-safe：未启用 / 空输入 / 整批网络失败 → {}；单条字段缺失/形状异常 →
        该市场 resolved=False（unknown），绝不抛异常、绝不阻断监测主流程。
        """
        return self.fetch_resolutions_answered(market_ids)[0]

    def fetch_resolutions_answered(
            self, market_ids: List[str]) -> Tuple[Dict[str, Dict[str, Any]], Set[str]]:
        """EVAL-2：``(fetch_resolutions 的结果, 判定源确实应答过的 market id 集合)``。

        应答 = 请求成功、响应是只含所请求 id 的市场列表，且返回了该行或经单 id 复查确认无此
        市场（见 ``_confirm_answered``）。失败批次（网络 / 5xx / 非列表响应）、未经复查确认的
        缺行与未启用时的 id 都不在集合里：结算据此只让「确认无数据」的条目走到 grace
        terminal，绝不因一次瞬时失败或被截断的页永久终结条目。"""
        ids: List[str] = []
        seen: set = set()
        for mid in market_ids or []:
            s = str(mid or "").strip()
            if s and s not in seen:
                seen.add(s)
                ids.append(s)
        answered: Set[str] = set()
        if not self.enabled or not ids:
            return {}, answered
        fresh = self._fetch_fresh_markets(ids, answered=answered)
        out: Dict[str, Dict[str, Any]] = {}
        for mid, raw in fresh.items():
            parsed = _parse_resolution(raw)
            if parsed is not None:
                out[mid] = parsed
        return out, answered

    @staticmethod
    def _normalize_market(raw: Any, matched_query: str,
                          event_title: str = "",
                          min_volume: float = 200,
                          event_slug: str = "") -> Optional[Dict[str, Any]]:
        """单条 Polymarket 市场规整化；不合格（已关闭/无价/定盘价/低量）返回 None。"""
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
        out: Dict[str, Any] = {
            "market_id": market_id,
            "exchange": "polymarket",
            "question": question,
            "implied_yes_prob": round(prob, 4),
            "volume": volume,
            "liquidity": liquidity,
            "event_title": event_title or str(raw.get("groupItemTitle") or "").strip(),
            "matched_query": matched_query,
        }
        # —— 富化字段：API 行里有才带上，缺失不造假（旧消费方按键存在性取用，schema 向后兼容）——
        if str(event_slug or "").strip():
            out["url"] = f"https://polymarket.com/event/{str(event_slug).strip()}"
        end_date = str(raw.get("endDate") or "").strip()
        if end_date:
            out["end_date"] = end_date  # 市场截止时间——锚点时效性判断的关键上下文
        for src_key, dst_key in (("oneDayPriceChange", "one_day_price_change"),
                                 ("bestBid", "best_bid"), ("bestAsk", "best_ask")):
            val = _coerce_float(raw.get(src_key))
            if val is not None:
                out[dst_key] = round(val, 4)
        # CLOB token id（Yes/No 各一）：画历史价时间线（fetch_price_history）与重报价核对的入口；
        # Gamma 里是 JSON 串 '["0x..","0x.."]'，规整成 list 保留；缺失不造假（键不出现）。
        # LOOP-017 P1（reversed-token 防线）：clobTokenIds 与 outcomes 是**位置对齐**的
        # （Gamma 契约），而市场偶有 ["No","Yes"] 排序——任何消费方都不得假设下标 0 是
        # Yes 腿。快照行额外带 outcomes 原名单（对齐可解释）+ 显式的 clob_yes_token_id
        # （按 "Yes" 下标定位；下标超出 token 范围时不造假，键不出现）。
        clob_ids = [str(t).strip() for t in _as_list(raw.get("clobTokenIds")) if str(t).strip()]
        outcome_names = [str(n).strip() for n in _as_list(raw.get("outcomes"))]
        if outcome_names:
            out["outcomes"] = outcome_names
        if clob_ids:
            out["clob_token_ids"] = clob_ids
            yes_idx = next((i for i, n in enumerate(outcome_names)
                            if n.lower() == "yes"), None)
            if yes_idx is not None and yes_idx < len(clob_ids):
                out["clob_yes_token_id"] = clob_ids[yes_idx]
        return out


# ------------------------------------------------------------------ rendering
def _esc_cell(x: Any) -> str:
    """markdown 表格单元转义（管道符/换行），与 forecast_extractor 同风格。"""
    return str(x).replace("|", "／").replace("\n", " ").strip()


def _requote_move(m: Dict[str, Any]) -> Optional[str]:
    """重报价后研究期价与现价不同 → 返回 '34%→41%'；无 price_at_research 或价未变 → None。"""
    r = _coerce_float(m.get("price_at_research"))
    c = _coerce_float(m.get("implied_yes_prob"))
    if r is None or c is None or round(r, 4) == round(c, 4):
        return None
    return f"{r * 100:.0f}%→{c * 100:.0f}%"


def _window_ended_label(m: Dict[str, Any], zh: bool) -> str:
    """TIME-3: suffix for a row stamped ``window_ended`` (its endDate passed, awaiting
    settlement); unstamped rows → "" so their cells stay byte-identical."""
    if m.get("window_ended") is not True:
        return ""
    end = parse_market_end(m.get("window_ended_at")) or _row_market_end(m)
    day = end.date().isoformat() if end is not None else ""
    if zh:
        return f" — 已过截止日 {day}，待结算" if day else " — 已过截止日，待结算"
    return (f" — window ended {day}, awaiting settlement" if day
            else " — window ended, awaiting settlement")


def render_markets_block(markets: List[Dict[str, Any]], lang: str = "en") -> str:
    """把市场快照渲染为确定性的 markdown 表（无 LLM；空列表 → ""，注入自动跳过）。

    若任一行经过重报价（有 price_at_research 且现价与之不同）→ 追加一列 Δ 展示
    '研究期价→现价'（如 34%→41%）；没有任何行发生移动时不加该列，与旧渲染逐字节一致。
    TIME-3：PREDICTION_MARKETS_END_DATE_GATE 开时先按 market_clock_now() 盖 window_ended 章
    （浅拷贝，调用方不变）；已盖章的行在问题单元格后追加「window ended YYYY-MM-DD, awaiting
    settlement」——行仍保留（其价格仍是证据），未盖章的输出逐字节不变。旗标关 → 不盖章也
    不标注（即便输入行带研究期的 window_ended 章），与旧渲染逐字节一致。
    """
    rows = [m for m in (markets or []) if isinstance(m, dict)]
    if not rows:
        return ""
    gate, grace = end_date_gate_settings()
    if gate:
        rows, _ = stamp_window_ended(rows, now=market_clock_now(), grace_hours=grace)
    zh = str(lang or "").lower().startswith("zh")
    show_delta = any(_requote_move(m) for m in rows)  # 有价格移动才加 Δ 列
    title = "### Prediction Market Signals (Polymarket)"
    if zh:
        headers = ["#", "市场问题", "交易所", "隐含 P(yes)"]
        if show_delta:
            headers.append("Δ（研究→现在）")
        headers.append("成交量")
        caveat = ("_以上为机器抓取的活跃市场快照，价格随时变动；市场隐含概率是校准锚点，"
                  "不是真值——引用前注意时效。_")
    else:
        headers = ["#", "Market question", "Venue", "Implied P(yes)"]
        if show_delta:
            headers.append("Δ (research→now)")
        headers.append("Volume")
        caveat = ("_Machine-fetched snapshot of active markets; prices move continuously. "
                  "Market-implied probabilities are calibration anchors, not ground truth — "
                  "mind freshness before relying on them._")
    cols = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join(["---"] * len(headers)) + "|"
    lines = [title, "", cols, sep]
    for i, m in enumerate(rows, 1):
        prob = _coerce_float(m.get("implied_yes_prob"))
        pct = f"{prob * 100:.0f}%" if prob is not None else "—"
        vol = _coerce_float(m.get("volume"))
        vol_s = f"{vol:,.0f}" if vol is not None else "—"
        q_cell = _esc_cell(str(m.get("question") or "")[:160])
        url = str(m.get("url") or "").strip()
        if url:  # 有事件 URL → 市场问题渲染为可点链接（读者可核对实时价格/规则）
            q_cell = f"[{q_cell}]({_esc_cell(url)})"
        cells = [str(i), f"{q_cell} ({_esc_cell(m.get('market_id') or '')})"
                 + (_window_ended_label(m, zh) if gate else ""),
                 _esc_cell(m.get("exchange") or "—"), pct]
        if show_delta:
            cells.append(_requote_move(m) or "—")  # 未移动/无锚点的行留占位符
        cells.append(vol_s)
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", caveat]
    return "\n".join(lines)


# ------------------------------------------------------------ query derivation
# 全文检索用「短词组」效果最好（如 'tariff' / 'semiconductor export' / 'AI capex'）；
# 从研究问题启发式抽取显著名词短语（停用词过滤，无需 LLM），再并入 hot_topics 与
# 高显著度 actor 名，去重后限量。确定性：同输入必得同输出。
_QUERY_STOPWORDS = frozenset("""
a an the and or but of to in on for with by from at as is are was were be been being
will would could should shall may might must can do does did not no nor this that these
those it its their his her our your my we they you he she i who whom whose which what
when where why how whether if than then so such very just now here there per via about
into over under between among during before after above below up down out off again
further once more most other some any all both each few own same too s t don also
year years month months week weeks day days future likely impact effect effects report
research question forecast prediction predict analysis analyze scenario scenarios
""".split())

# 英文/数字词、4 位年份（如 2026——市场标题几乎总带结算年份，必须保留）或
# 连续 CJK 串（CJK 不按空格分词，整段作为一个候选 token）。
_QUERY_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]*|(?<!\d)\d{4}(?!\d)|[一-鿿]{2,}")

# 泛化空词黑名单：这些词在市场标题全文检索里零区分度（搜 "key factors impact" 命中不了
# 任何市场），与停用词同等对待、且作为短语边界（部分与停用词重叠是刻意的显式声明）。
_QUERY_GENERIC_BLACKLIST = frozenset("""
outcome outcomes cover covers covering key factor factors impact impacts
effect effects implication implications
""".split())

# 子句边界（中英逗号/分号/句号/问号/括号/引号等）：显著短语不得跨子句拼接——
# "tariffs rise, china retaliates" 应产出两个短语，而非无意义的 "rise china"。
_CLAUSE_SPLIT_RE = re.compile(r"[,;:.!?，、。；：！？…()（）【】\[\]{}<>\"“”‘’]+")


def _salient_phrases(text: str, max_words: int = 3) -> List[str]:
    """从文本抽取显著短语：**子句内**连续的非停用词 token 聚成 ≤max_words 词的短语
    （确定性启发式；子句边界强制断句，短语绝不跨逗号/句号等标点拼接）。"""
    phrases: List[str] = []
    cur: List[str] = []

    def _flush() -> None:
        if cur:
            phrases.append(" ".join(cur))
            cur.clear()

    for clause in _CLAUSE_SPLIT_RE.split(str(text or "")):
        for tok in _QUERY_TOKEN_RE.findall(clause):
            is_cjk = bool(re.match(r"[一-鿿]", tok))
            if is_cjk:
                cur.append(tok[:12])  # CJK 串过长时截断（全文检索短词更有效）
                _flush()
                continue
            low = tok.lower()
            # 全大写缩略词（AI/EU/GDP）即使短也保留；其余 <3 字符的英文词按噪声丢弃。
            if (low in _QUERY_STOPWORDS or low in _QUERY_GENERIC_BLACKLIST
                    or (len(tok) < 3 and not tok.isupper())):
                _flush()
                continue
            cur.append(tok)
            if len(cur) >= max_words:
                _flush()
        _flush()  # 子句结束 → 强制断句
    # 去重保序
    seen: set = set()
    out: List[str] = []
    for p in phrases:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def derive_market_queries(question: str, hot_topics: Optional[List[str]] = None,
                          actor_names: Optional[List[str]] = None,
                          max_queries: int = 12, max_words: int = 5) -> List[str]:
    """确定性派生市场检索词：研究问题关键短语 + hot_topics + 高显著度 actor 名。

    每条 ≤max_words 词（全文检索短词效果最好），去重限量到 max_queries；为 actor 名
    保留 ≥2 个名额（主要主体的名字是最强的市场检索词，不得被短语/话题挤出）。
    纯启发式、无 LLM 调用；空输入返回 []。
    """
    out: List[str] = []
    seen: set = set()

    def _add(q: Any, limit: int) -> None:
        s = re.sub(r"\s+", " ", str(q or "")).strip(" \t\"'.,;:!?()[]{}")
        if not s:
            return
        words = s.split()
        if len(words) > max_words:
            s = " ".join(words[:max_words])
        k = s.lower()
        if k in seen or len(out) >= limit:
            return
        seen.add(k)
        out.append(s)

    actors = [a for a in (actor_names or []) if str(a or "").strip()][:3]
    reserved = min(2, len(actors))  # actor 名保留名额（≤2，按实际 actor 数收缩）
    general_cap = max(0, max_queries - reserved)
    for ph in _salient_phrases(question, max_words=3)[:6]:
        _add(ph, general_cap)
    for t in (hot_topics or [])[:6]:
        _add(t, general_cap)
    for n in actors:
        _add(n, max_queries)
    return out


# LLM 派生检索词的条数窗口：Polymarket 全文检索召回窄，10~16 条「市场标题形」检索词
# 才能覆盖一个多面研究问题的各个可下注侧面。
_LLM_QUERY_MIN = 10
_LLM_QUERY_MAX = 16


def _clean_query(q: Any, max_words: int = 8) -> str:
    """单条检索词清洗：压空白、剥引号/标点、截到 ≤max_words 词；无效返回 ""。"""
    s = re.sub(r"\s+", " ", str(q or "")).strip(" \t\"'.,;:!?()[]{}")
    words = s.split()
    return " ".join(words[:max_words]) if words else ""


def derive_market_queries_llm(llm_call: Any, question: str,
                              hot_topics: Optional[List[str]] = None,
                              actors: Optional[List[str]] = None) -> List[str]:
    """LLM 派生市场检索词（provider-agnostic：llm_call 接收 prompt 字符串、返回文本）。

    启发式短语（如 "semiconductor export controls"）常与真实市场标题的措辞对不上
    （市场写的是 "Will the US ban Nvidia chip sales to China in 2026?"）；让 LLM 把研究
    问题翻译成 10~16 条「市场标题形」的短检索词能显著提升召回。JSON 解析鲁棒（容忍
    代码栅栏/散文包裹/{"queries": [...]} 包装/字典元素）；产出不足时用启发式确定性补足。
    Degrade-safe：llm_call 为 None/不可调用/抛异常/完全不可解析 → 回退
    derive_market_queries 启发式（今天的行为），绝不抛异常。
    """
    fallback = derive_market_queries(question, hot_topics=hot_topics,
                                     actor_names=actors, max_queries=12)
    if llm_call is None or not callable(llm_call) or not str(question or "").strip():
        return fallback
    try:
        topics_line = ", ".join(str(t) for t in (hot_topics or [])[:8] if str(t or "").strip())
        actors_line = ", ".join(str(a) for a in (actors or [])[:8] if str(a or "").strip())
        prompt = (
            "You generate full-text search queries for Polymarket (a prediction market).\n"
            f"Research question: {str(question).strip()}\n"
            + (f"Hot topics: {topics_line}\n" if topics_line else "")
            + (f"Key actors: {actors_line}\n" if actors_line else "")
            + f"\nProduce {_LLM_QUERY_MIN}-{_LLM_QUERY_MAX} short queries (2-6 words each) "
            "phrased the way prediction-market titles are phrased: concrete events, named "
            "actors, numbers/dates (e.g. \"Fed rate cut 2026\", \"China Taiwan blockade\", "
            "\"US recession 2026\"). Cover the question's distinct bettable angles; no "
            "duplicates, no generic filler words.\n"
            "Return ONLY a JSON array of strings, no prose."
        )
        payload = _extract_json_payload(llm_call(prompt))
        if isinstance(payload, dict):  # 容忍 {"queries": [...]} 包装
            payload = payload.get("queries")
        queries: List[str] = []
        seen: set = set()

        def _push(candidate: Any) -> None:
            s = _clean_query(candidate)
            if s and s.lower() not in seen and len(queries) < _LLM_QUERY_MAX:
                seen.add(s.lower())
                queries.append(s)

        for item in payload if isinstance(payload, list) else []:
            if isinstance(item, dict):  # 容忍 [{"query": "..."}] 形状
                item = item.get("query") or item.get("q") or item.get("title")
            if isinstance(item, (str, int, float)):
                _push(item)
        if not queries:
            return fallback
        for fq in fallback:  # 产出不足 → 用启发式确定性补足到下限
            if len(queries) >= _LLM_QUERY_MIN:
                break
            _push(fq)
        return queries
    except Exception as e:  # noqa: BLE001 — LLM 派生失败绝不阻断：回退确定性启发式
        logger.warning(f"LLM 市场检索词派生失败（回退启发式）: {e}")
        return fallback


# ---------------------------------------------------------- relevance scoring
def score_market_relevance(llm_call: Any, question: str,
                           markets: List[Dict[str, Any]],
                           min_relevance: Optional[float] = None) -> List[Dict[str, Any]]:
    """一次批量 LLM 调用给市场按题目相关性打 0~10 分，过滤 + 重排（可选增强）。

    全文检索召回的市场常与研究问题只沾边（搜 "Fed" 会命中体育/娱乐盘口）；单次批量
    打分（llm_call 接收 prompt 字符串、返回文本，provider-agnostic）后：
      * 得分 < min_relevance（默认 Config.PREDICTION_MARKETS_MIN_RELEVANCE=5）→ 剔除；
      * 通过者写入 relevance_score（0~10）+ relevance_rationale（一句话理由）；
      * 按 (relevance_score, volume) 双键降序重排（相关性优先，同分看成交量）。
    Degrade-safe：llm_call=None / 空列表 / 调用抛异常 / 回复完全不可解析 → 原列表
    原顺序返回（今天的 volume-only 行为）；个别市场缺分 → 保留该行并按门槛分参与排序
    （不因打分覆盖不全而丢真实信号）。不改传入行（返回打分行的浅拷贝）。
    """
    rows = [m for m in (markets or []) if isinstance(m, dict)]
    if llm_call is None or not callable(llm_call) or not rows or not str(question or "").strip():
        return rows
    try:
        threshold = float(min_relevance if min_relevance is not None
                          else _cfg("PREDICTION_MARKETS_MIN_RELEVANCE", 5.0))
    except (TypeError, ValueError):
        threshold = 5.0
    try:
        listing = "\n".join(
            f'- market_id={m.get("market_id")}: {str(m.get("question") or "")[:160]}'
            for m in rows)
        prompt = (
            "Score how relevant each prediction market is to the research question, "
            "0-10 (10 = directly bets on the question's outcome, 0 = unrelated).\n"
            f"Research question: {str(question).strip()}\n\nMarkets:\n{listing}\n\n"
            "Return ONLY a JSON array like "
            '[{"market_id": "...", "score": 7, "rationale": "one short sentence"}] '
            "covering every market, no prose."
        )
        payload = _extract_json_payload(llm_call(prompt))
        if isinstance(payload, dict):  # 容忍 {"scores": [...]} / {"markets": [...]} 包装
            payload = payload.get("scores") or payload.get("markets")
        scores: Dict[str, Any] = {}
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict):
                continue
            mid = str(item.get("market_id") or item.get("id") or "").strip()
            sc = _coerce_float(item.get("score", item.get("relevance")))
            if not mid or sc is None:
                continue
            scores[mid] = (max(0.0, min(10.0, sc)),
                           str(item.get("rationale") or "").strip()[:200])
        if not scores:
            return rows  # 整批解析失败 → 保持今天的 volume 排序
        kept: List[Dict[str, Any]] = []
        for m in rows:
            got = scores.get(str(m.get("market_id") or "").strip())
            if got is None:
                kept.append(m)  # 未被覆盖的行保留（degrade-safe，不因缺分丢信号）
                continue
            sc, why = got
            if sc < threshold:
                continue  # 低相关市场剔除——错误锚点比没有锚点更糟
            m2 = dict(m)
            m2["relevance_score"] = round(sc, 1)
            if why:
                m2["relevance_rationale"] = why
            kept.append(m2)

        def _rank_key(m: Dict[str, Any]) -> Any:
            sc = _coerce_float(m.get("relevance_score"))
            # 缺分行按门槛分参与排序（既不置顶也不垫底），同分内仍按 volume 降序。
            return (-(sc if sc is not None else threshold),
                    -(_coerce_float(m.get("volume")) or 0.0))

        kept.sort(key=_rank_key)
        return kept
    except Exception as e:  # noqa: BLE001 — 打分失败绝不阻断：保持 volume-only 排序
        logger.warning(f"市场相关性打分失败（保持 volume 排序）: {e}")
        return rows
