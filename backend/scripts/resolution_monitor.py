"""MON-1 解析追踪 / 持续预测监测（cron 驱动的 CLI）

把「一次性发布的预测报告」升级为「持续被真实世界打分的持仓」：对一份已发布报告里
**锚定了真实预测市场**的二元预测，周期性地——

1. 重报价锚点市场（复用 PolymarketClient.requote_markets），把「研究期价 → 现价」的漂移
   追加成一条带时间戳的快照，落 per-report ``price_track.jsonl``；
2. 判定检查：查询 Gamma 每个锚点市场的 closed/resolved 终态
   （PolymarketClient.fetch_resolutions）；市场一旦判定，模型概率就有了真值标签，回算
   Brier 并把 {forecast_id, market_id, resolved_outcome, model_p, market_p_at_research,
   brier_contribution, resolved_at} 幂等入账到 forecast_ledger 的 ``resolutions.jsonl``；
3. 指标检查（尽力而为）：二元预测带 dated 判定标准（horizon_year / resolution_criteria）；
   凡 resolution_date 已过、却无市场判定可依的，列入「需人工判定」清单；
4. 汇总成 ``monitor_report.md``——研究以来的价格漂移（biggest movers）、本次新判定、
   需人工判定清单、结算计数（## Settlement）、以及账本里的持续 Brier / 校准。

EVAL-2（settlement events v2，确定性、无 LLM）：
- 先过两道 fail-closed 闸门，未过则零写盘、零网络：报告须「发布时可发布」
  （ReportManager.publishable_at_issue——只忽略事后策略版本升级这一条理由），且
  forecast.json 须被最终审计封印（load_structured_forecast(allow_stale_policy=True)）；
  否则返回 ``{skipped: 'not_publishable' | 'not_sealed'}``。
- 判定由 app.services.forecast_resolution.settle_binaries 决定：已判定 / 50-50 模糊判定的
  市场写 schema_version 2 事件（outcome_known_at 取 Gamma closedTime，缺失/晚于处理时刻则
  以处理时刻为上界，绝不取 endDate；prospective 需下界证明；scoring_eligible 需精确、
  字节绑定、截止日一致的锚点）；未关闭 / UMA 提议或争议中 / 价未收敛 → pending 按原因计数；
  判定日（二元预测写出的所有日期——ISO、「2028年12月31日」「June 30, 2027」「Q2 2027」等
  各种写法——与 horizon_year 年底中最晚的一个）+ RESOLUTION_PENDING_GRACE_DAYS 仍无判定
  → 一条永不计分的 terminal 事件（判定源未应答的市场绝不终结）；已有 terminal 的条目
  即为终态，之后市场再判定也不追加第二条事实（计入 already_terminal）。
  事件仍落 resolutions.jsonl，幂等键 (report_id, forecast_id, market_id) 与文件锁不变。
  只有生产 primary 目标的结算入账：ensemble / what-if / comparison / revision / evaluation
  报告（生产或 evaluation 账本里有行、却无生产 primary commit）照算照报、一条不写。
- ``settle`` 子命令：扫描账本里的生产 primary commit 行（自包含 binary_forecasts，
  报告目录已删也能结算），只处理本轮可处理的条目（未入账，且有市场锚点、或无锚点且已过
  grace），批量查判定并追加事件；RESOLUTION_SETTLE_MAX_TARGETS 只限需联网查判定的行，
  判定日已过的锚定行最早逾期者优先，其余新到旧；已过 grace 的无锚点条目不受上限
  （terminal 不需要网络）；
  RESOLUTION_SETTLE_LEDGER=true（默认）时 ``run --all-recent`` 在逐报告循环后也跑一次。
  ensemble / evaluation 行永不扫描。

设计与 scripts/scheduled_rerun.py 同构：脚本自撑 sys.path、Config 旋钮经 getattr 读取
（本文件不拥有 config.py）、全链路 degrade-safe——任何网络失败只产出**部分**报告，
绝不抛异常、绝不改动任何在线管线语义。``--dry-run`` 全程不写盘（纯观测）。

命令行
------
    python scripts/resolution_monitor.py run <report_id|pipeline_id> [--dry-run]
    python scripts/resolution_monitor.py run --all-recent [N] [--dry-run]   # 最近 N 份报告（缺省 N=RESOLUTION_MONITOR_RECENT_N）
    python scripts/resolution_monitor.py settle [--dry-run]                 # EVAL-2：扫描账本 primary commit 行并追加结算事件
    python scripts/resolution_monitor.py summary                            # 只打印账本里的持续 Brier / 校准（无网络）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

# ── 让脚本无论从哪个 cwd 调用都能 import 到 backend 的 app 包（与 scheduled_rerun.py 一致）──
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.config import Config  # noqa: E402
from app.services import forecast_ledger as _ledger  # noqa: E402
from app.services import forecast_resolution as _settlement  # noqa: E402
from app.utils.logger import get_logger  # noqa: E402
from app.utils.point_in_time import parse_stamp_strict  # noqa: E402

logger = get_logger("mirofish.resolution_monitor")


# ---------------------------------------------------------------------------
# Config 旋钮（经 getattr 读取，本文件不拥有 config.py；缺失时用下方默认，行为不变）
# ---------------------------------------------------------------------------


def _cfg_int(name: str, default: int) -> int:
    try:
        return int(getattr(Config, name, default))
    except (TypeError, ValueError):
        return default


def _cfg_float(name: str, default: float) -> float:
    try:
        return float(getattr(Config, name, default))
    except (TypeError, ValueError):
        return default


def recent_n_default() -> int:
    return max(1, _cfg_int("RESOLUTION_MONITOR_RECENT_N", 10))


def lookback_days() -> int:
    return max(0, _cfg_int("RESOLUTION_MONITOR_LOOKBACK_DAYS", 0))


def drift_threshold() -> float:
    t = _cfg_float("RESOLUTION_MONITOR_DRIFT_THRESHOLD", 0.05)
    # 阈值取 [0,1]；非法值回退默认，避免负阈值把所有行都算成 mover。
    return t if 0.0 <= t <= 1.0 else 0.05


def settle_ledger_enabled() -> bool:
    """EVAL-2：run --all-recent 结束后是否再扫一遍账本 primary commit 行（默认开）。"""
    return bool(getattr(Config, "RESOLUTION_SETTLE_LEDGER", True))


def market_min_equivalence() -> str:
    """EVAL-2：可计分结算要求的最弱锚点等价度；非法值按最严的 exact（fail closed）。
    loose 与 near 等效：loose / 缺失等价度的锚点在完整性检查就判 anchor_incomplete。"""
    eq = str(getattr(Config, "RESOLUTION_MARKET_MIN_EQUIVALENCE", "exact") or "").strip().lower()
    return eq if eq in ("exact", "near", "loose") else "exact"


def pending_grace_days() -> int:
    return max(0, _cfg_int("RESOLUTION_PENDING_GRACE_DAYS", 180))


def settle_max_targets() -> int:
    return max(1, _cfg_int("RESOLUTION_SETTLE_MAX_TARGETS", 200))


# ---------------------------------------------------------------------------
# 小工具（本地实现，避免与 utils/prediction_markets 强耦合；degrade-safe）
# ---------------------------------------------------------------------------


def _coerce_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return None if f != f else f  # NaN → None
    except (TypeError, ValueError):
        return None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# A naive ISO date or date-time (no zone) — read as UTC by normalize_processed_at.
_NAIVE_STAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?)?", re.ASCII)


def normalize_processed_at(value: Any) -> str:
    """EVAL-2：把监测的 as_of 规整为带时区的 UTC ISO 串（结算事件的 processed_at）。

    带 Z/偏移的时刻换算到 UTC；无时区的 ISO 日期/时刻按 UTC 读（如 '2026-07-07T00:00:00'
    → '2026-07-07T00:00:00+00:00'）。结算判定只读这一个时钟，故可复现。其他值 → ValueError。"""
    moment = parse_stamp_strict(value)
    if moment is None and isinstance(value, str) and _NAIVE_STAMP_RE.fullmatch(value):
        try:
            moment = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        except ValueError:
            moment = None
    if moment is None:
        raise ValueError(f"as_of is not an ISO date or date-time: {value!r}")
    return moment.isoformat()


def _local_stamp_to_utc(value: Any) -> Optional[str]:
    """meta.json 的 created_at 由 datetime.now().isoformat() 写出（主机本地时间、无时区）：
    无时区按本地时间读并换算 UTC；带时区直接换算；其他 → None。"""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip()).astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def _read_json(path: str) -> Optional[Any]:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 报告 / 管线定位（延迟导入 ReportManager / PipelineManager，避免脚本层硬依赖）
# ---------------------------------------------------------------------------


def _report_folder(report_id: str) -> str:
    """报告文件夹路径（uploads/reports/<report_id>）。"""
    from app.services.report_agent import ReportManager
    return ReportManager._get_report_folder(report_id)


def resolve_report_id(id_: str) -> Optional[str]:
    """把用户传入的 id 归一到 report_id：先当报告目录看，命中即用；否则当 pipeline_id
    去 PipelineManager 取其 report_id。都不命中 → None。"""
    rid = str(id_ or "").strip()
    if not rid:
        return None
    try:
        if os.path.isdir(_report_folder(rid)):
            return rid
    except Exception:  # noqa: BLE001 — ReportManager 不可用时转 pipeline 路径
        pass
    try:
        from app.services.pipeline_orchestrator import PipelineManager
        data = PipelineManager.load(rid)
        if data and data.get("report_id"):
            return str(data["report_id"])
    except Exception:  # noqa: BLE001
        return None
    return None


def recent_report_ids(n: int, *, as_of: Optional[str] = None) -> List[str]:
    """最近 n 份报告的 report_id（按 created_at 倒序，与 ReportManager.list_reports 同序）。
    RESOLUTION_MONITOR_LOOKBACK_DAYS>0 时进一步过滤到 created_at 在近 N 天内的报告。"""
    try:
        from app.services.report_agent import ReportManager
        reports = ReportManager.list_reports(limit=max(1, int(n)))
    except Exception as e:  # noqa: BLE001 — 列报告失败 → 空（degrade-safe）
        logger.warning(f"列出最近报告失败（返回空）: {e}")
        return []
    ld = lookback_days()
    cutoff: Optional[str] = None
    if ld > 0:
        base = as_of or _today()
        try:
            from datetime import date, timedelta
            cutoff = (date.fromisoformat(str(base)[:10]) - timedelta(days=ld)).isoformat()
        except (TypeError, ValueError):
            cutoff = None
    out: List[str] = []
    for r in reports:
        if cutoff is not None and str(getattr(r, "created_at", "") or "")[:10] < cutoff:
            continue
        rid = getattr(r, "report_id", None)
        if rid:
            out.append(str(rid))
    return out


# ---------------------------------------------------------------------------
# 纯函数（无 I/O / 无网络）——便于离线单测
# ---------------------------------------------------------------------------


def anchored_forecasts(forecast: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从 forecast.json 取「带有效市场锚点」的二元预测（market_anchor.market_id 非空）。"""
    if not isinstance(forecast, dict):
        return []
    out: List[Dict[str, Any]] = []
    for b in (forecast.get("binary_forecasts") or []):
        if not isinstance(b, dict):
            continue
        anchor = b.get("market_anchor")
        if isinstance(anchor, dict) and str(anchor.get("market_id") or "").strip():
            out.append(b)
    return out


# 二元预测判定日（显式 ISO 日期优先，否则 horizon_year 年底）。EVAL-1：实现原样迁入
# forecast_ledger，供账本行自描述；此处保留同名别名，既有调用方与测试不变。
binary_resolution_date = _ledger.binary_resolution_date


def build_price_rows(anchored: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把锚定预测拍平成 requote_markets 的输入行（每条预测一行，携带回填所需上下文）。"""
    rows: List[Dict[str, Any]] = []
    for b in anchored:
        a = b.get("market_anchor") or {}
        mid = str(a.get("market_id") or "").strip()
        if not mid:
            continue
        research = _coerce_float(a.get("price_at_research"))
        if research is None:
            research = _coerce_float(a.get("implied_yes_prob"))
        rows.append({
            "market_id": mid,
            "question": a.get("question"),
            "implied_yes_prob": _coerce_float(a.get("implied_yes_prob")),
            "price_at_research": research,
            "forecast_id": b.get("id"),
            "statement": b.get("statement"),
        })
    return rows


def compute_movers(requoted: List[Dict[str, Any]],
                   threshold: float) -> List[Dict[str, Any]]:
    """从重报价后的行里挑出价格漂移达阈值的 movers，按 |Δ| 降序（研究期价→现价）。"""
    movers: List[Dict[str, Any]] = []
    for m in requoted or []:
        if m.get("requote_failed"):
            continue
        delta = _coerce_float(m.get("price_delta"))
        if delta is None or abs(delta) < float(threshold):
            continue
        movers.append({
            "market_id": m.get("market_id"),
            "forecast_id": m.get("forecast_id"),
            "statement": m.get("statement"),
            "price_at_research": _coerce_float(m.get("price_at_research")),
            "current": _coerce_float(m.get("implied_yes_prob")),
            "delta": round(delta, 4),
        })
    movers.sort(key=lambda x: -(abs(x.get("delta") or 0.0)))
    return movers


def build_resolution_records(anchored: List[Dict[str, Any]],
                             resolutions: Dict[str, Dict[str, Any]],
                             *, report_id: str, resolved_at: str) -> List[Dict[str, Any]]:
    """对每条锚定预测：若其锚点市场已判定（YES/NO 收敛且 UMA 非提议/争议中），回算 Brier。

    EVAL-2：薄封装——判定逻辑统一在 forecast_resolution.settle_binaries（本函数只取其中
    resolution_status='settled' 的市场事件；50/50 模糊判定、pending 与 terminal 不在此列）。
    y（真值）取自市场终态：resolved_yes_price ≥ 0.5 ⇒ y=1，否则 y=0；
    brier_contribution = (model_p − y)²。纯函数、可离线单测。"""
    out = _settlement.settle_binaries(
        report_id, list(anchored or []), resolutions,
        processed_at=normalize_processed_at(resolved_at),
        min_equivalence=market_min_equivalence(), grace_days=pending_grace_days())
    return [e for e in out["events"] if e.get("resolution_status") == "settled"]


def detect_needs_manual(binaries: List[Dict[str, Any]],
                        resolved_market_ids: set,
                        as_of: str) -> List[Dict[str, Any]]:
    """指标检查：判定日期已过（≤ as_of）但无市场判定可依的二元预测 → 需人工判定。

    「有市场判定可依」= 该预测锚点市场已 resolved。无锚点、或锚点市场尚未判定，且判定日期
    已过 → 列入清单。纯函数（对**全部**二元预测扫描，不止锚定的那些）。"""
    out: List[Dict[str, Any]] = []
    for b in binaries or []:
        if not isinstance(b, dict):
            continue
        rd = binary_resolution_date(b)
        if not rd or str(rd) > str(as_of):
            continue  # 无日期 或 尚未到期 → 不催
        anchor = b.get("market_anchor") or {}
        mid = str(anchor.get("market_id") or "").strip()
        if mid and mid in resolved_market_ids:
            continue  # 市场已给出判定，无需人工
        out.append({
            "forecast_id": b.get("id"),
            "statement": b.get("statement"),
            "resolution_date": rd,
            "resolution_criteria": b.get("resolution_criteria"),
            "has_anchor": bool(mid),
        })
    return out


def _pct(v: Optional[float]) -> str:
    return f"{v * 100:.0f}%" if isinstance(v, (int, float)) else "—"


def _cell(x: Any) -> str:
    return str(x).replace("|", "／").replace("\n", " ").strip()


def _reason_counts(counts: Any) -> str:
    """{reason: n} → 'market_open 2, uma_pending 1'（按原因名排序）；空 → '—'。"""
    if not isinstance(counts, dict) or not counts:
        return "—"
    return ", ".join(f"{_cell(k)} {v}" for k, v in sorted(counts.items()))


def _render_settlement(settlement: Dict[str, Any],
                       events: List[Dict[str, Any]]) -> List[str]:
    """EVAL-2 「## Settlement」段：结算计数 + 本次结算 / terminal 事件明细。"""
    lines = [
        "", "## Settlement", "",
        f"- Settled YES/NO: **{settlement.get('settled', 0)}**; scoring-eligible: "
        f"**{settlement.get('settled_eligible', 0)}**",
        f"- Ambiguous 50/50 settlements (never scored): **{settlement.get('ambiguous', 0)}**",
        f"- Terminal, unresolvable after grace (never scored): "
        f"**{settlement.get('terminal', 0)}**",
        f"- Already terminal (final; a later settlement is not recorded): "
        f"**{settlement.get('already_terminal', 0)}**",
        f"- Pending by reason: {_reason_counts(settlement.get('pending_by_reason'))}",
        f"- Ineligible by reason: {_reason_counts(settlement.get('ineligible_by_reason'))}",
        f"- Events appended this run: **{settlement.get('appended', 0)}**",
    ]
    if settlement.get("not_recorded"):
        lines.append(f"- Not recorded in resolutions.jsonl: {_cell(settlement['not_recorded'])} "
                     "(only a production primary forecast's settlement is recorded)")
    if events:
        lines += ["", "| Forecast | Market | Status | Outcome | Known at (basis) | "
                      "Prospective | Scoring |",
                  "|---|---|---|---|---|---|---|"]
        for e in events:
            known = e.get("outcome_known_at")
            known_s = f"{known} ({e.get('known_at_basis')})" if known else "—"
            scoring = "eligible" if e.get("scoring_eligible") else (
                f"no: {e.get('ineligible_reason') or '—'}")
            prospective = e.get("prospective")
            lines.append(
                "| " + " | ".join([
                    _cell(e.get("forecast_id") or ""),
                    _cell(e.get("market_id") or ""),
                    _cell(e.get("resolution_status") or "—"),
                    _cell(e.get("outcome") or "—"),
                    _cell(known_s),
                    _cell("—" if prospective is None else prospective),
                    _cell(scoring),
                ]) + " |")
    return lines


def render_monitor_md(*, report_id: str, as_of: str,
                      movers: List[Dict[str, Any]],
                      resolution_records: List[Dict[str, Any]],
                      needs_manual: List[Dict[str, Any]],
                      calibration: Dict[str, Any],
                      market_brier: Dict[str, Any],
                      anchored_count: int,
                      degraded: bool,
                      settlement: Optional[Dict[str, Any]] = None,
                      settlement_events: Optional[List[Dict[str, Any]]] = None) -> str:
    """把一次监测结果渲染成确定性 markdown（无 LLM）。空信号也产出可读骨架。

    EVAL-2：传入 ``settlement``（结算计数）时追加「## Settlement」段；缺省 None → 输出不变。"""
    lines: List[str] = [
        f"# Resolution Monitor — {report_id}",
        "",
        f"_As of {as_of} (UTC). Anchored binary forecasts tracked: {anchored_count}._",
    ]
    if degraded:
        lines.append("")
        lines.append("> ⚠ Prediction-market access degraded (disabled or network failure) — "
                     "price drift and market resolutions may be partial this run.")

    # ── 持续 Brier / 校准（账本口径）──
    mb = market_brier.get("mean_brier")
    mb_n = market_brier.get("n_resolved") or 0
    cb = calibration.get("mean_brier")
    cb_n = calibration.get("n_resolved") or 0
    ce = calibration.get("calibration_error")
    lines += [
        "",
        "## Running score (from ledger)",
        "",
        f"- Market-resolved binary forecasts: **{mb_n}**; mean Brier: "
        f"**{mb if mb is not None else '—'}**",
        f"- Scenario forecasts resolved: **{cb_n}**; mean Brier: "
        f"**{cb if cb is not None else '—'}**; calibration error: "
        f"**{ce if ce is not None else '—'}**",
    ]

    # ── 本次新判定 ──
    lines += ["", "## Newly resolved markets", ""]
    if resolution_records:
        lines.append("| Forecast | Market | Outcome | Model P | Brier |")
        lines.append("|---|---|---|---|---|")
        for r in resolution_records:
            lines.append(
                "| " + " | ".join([
                    _cell(r.get("forecast_id") or ""),
                    _cell(r.get("market_id") or ""),
                    _cell(r.get("resolved_outcome") or "—"),
                    _pct(r.get("model_p")),
                    _cell(r.get("brier_contribution")
                          if r.get("brier_contribution") is not None else "—"),
                ]) + " |")
    else:
        lines.append("_No anchored market resolved as of this run._")

    if settlement is not None:
        lines += _render_settlement(settlement, list(settlement_events or []))

    # ── 价格漂移（biggest movers）──
    lines += ["", "## Biggest price movers since research", ""]
    if movers:
        lines.append("| Market | Forecast | Research P | Now P | Δ |")
        lines.append("|---|---|---|---|---|")
        for m in movers:
            d = m.get("delta")
            d_s = f"{d * 100:+.0f}pt" if isinstance(d, (int, float)) else "—"
            lines.append(
                "| " + " | ".join([
                    _cell(m.get("market_id") or ""),
                    _cell(str(m.get("statement") or "")[:80]),
                    _pct(m.get("price_at_research")),
                    _pct(m.get("current")),
                    d_s,
                ]) + " |")
    else:
        lines.append("_No anchored market moved beyond the drift threshold._")

    # ── 需人工判定 ──
    lines += ["", "## Needs manual resolution", ""]
    if needs_manual:
        lines.append("| Forecast | Resolution date | Has market anchor | Criteria |")
        lines.append("|---|---|---|---|")
        for n in needs_manual:
            lines.append(
                "| " + " | ".join([
                    _cell(n.get("forecast_id") or ""),
                    _cell(n.get("resolution_date") or "—"),
                    "yes" if n.get("has_anchor") else "no",
                    _cell(str(n.get("resolution_criteria") or "")[:80]),
                ]) + " |")
    else:
        lines.append("_No forecast is past its resolution date without a market resolution._")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# per-report price_track.jsonl（带时间戳的价格快照追加日志）
# ---------------------------------------------------------------------------


def price_track_path(report_folder: str) -> str:
    return os.path.join(report_folder, "price_track.jsonl")


def append_price_snapshot(report_folder: str, snapshot: Dict[str, Any]) -> bool:
    """把一条价格快照追加进 per-report price_track.jsonl。失败仅告警、返回 False。"""
    try:
        os.makedirs(report_folder, exist_ok=True)
        with open(price_track_path(report_folder), "a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
        return True
    except OSError as e:
        logger.warning(f"追加 price_track.jsonl 失败（忽略）: {e}")
        return False


def read_price_track(report_folder: str) -> List[Dict[str, Any]]:
    """读取 price_track.jsonl（容忍损坏尾行；缺失 → []）。"""
    out: List[Dict[str, Any]] = []
    path = price_track_path(report_folder)
    if not os.path.exists(path):
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except (ValueError, TypeError):
                    continue
    except OSError:
        return out
    return out


def _price_snapshot(report_id: str, as_of: str,
                    requoted: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把重报价后的行压成一条精简快照（只留价格追踪需要的字段）。"""
    markets = []
    for m in requoted or []:
        markets.append({
            "market_id": m.get("market_id"),
            "price_at_research": _coerce_float(m.get("price_at_research")),
            "implied_yes_prob": _coerce_float(m.get("implied_yes_prob")),
            "price_delta": _coerce_float(m.get("price_delta")),
            "requote_failed": bool(m.get("requote_failed")),
        })
    return {"at": as_of, "report_id": report_id, "markets": markets}


# ---------------------------------------------------------------------------
# EVAL-2：结算闸门 / 目标元数据 / 事件入账
# ---------------------------------------------------------------------------


def _publishable_at_issue(report_id: str) -> bool:
    """缺省发布闸门：ReportManager.publishable_at_issue（只忽略事后策略版本升级）。"""
    from app.services.report_agent import ReportManager
    return bool(ReportManager.publishable_at_issue(report_id).get("publishable"))


def _is_publishable(report_id: str, publishable_fn: Any) -> bool:
    """发布闸门求值；闸门自身出错按「不可发布」处理（fail closed）。"""
    fn = publishable_fn if publishable_fn is not None else _publishable_at_issue
    try:
        return bool(fn(report_id))
    except Exception as e:  # noqa: BLE001 — 无法证明可发布 → 不结算
        logger.warning(f"发布状态校验失败（按不可发布处理）: {report_id}: {e}")
        return False


def _load_sealed_forecast(report_id: str) -> Optional[Dict[str, Any]]:
    """只读被最终审计封印的 forecast.json（容忍事后策略版本升级）；未封印 → None。"""
    from app.services.report_agent import ReportManager
    return ReportManager.load_structured_forecast(report_id, allow_stale_policy=True)


def _is_production_primary(row: Any) -> bool:
    """生产 primary commit 行：唯一可被生产校准计分的预测目标（I-21）。"""
    return (isinstance(row, dict) and row.get("row_type") == "commit"
            and row.get("calibration_role") == "primary"
            and _ledger.is_production_calibration_row(row))


def _commit_target_meta(row: Dict[str, Any], *,
                        production_primary: bool = True) -> Dict[str, Any]:
    """账本 commit 行 → 结算用的预测原点 {as_of, created_at, commit_id, production_primary}。"""
    return {"as_of": row.get("as_of_date"), "created_at": row.get("created_at"),
            "commit_id": row.get("commit_id"), "production_primary": production_primary}


def _report_ledger_rows(report_id: str, ledger_dir: Optional[str]) -> List[Dict[str, Any]]:
    """一份报告在生产账本与 evaluation 账本里的全部行。evaluation 类行按 Foglamp WP1 的
    record_class 重定向（forecast_ledger._route_dir，此处复用同一规则）落在
    evaluation_ledger_dir()；注入的非缺省 ledger_dir 不重定向，evaluation 行就在它自己里面。
    两处都读才能认出 evaluation / golden 报告。"""
    dirs: List[str] = []
    for d in (ledger_dir or _ledger.ledger_dir(), _ledger._route_dir(ledger_dir, "evaluation")):
        if os.path.abspath(d) not in {os.path.abspath(x) for x in dirs}:
            dirs.append(d)
    return [row for d in dirs for row in _ledger.read_ledger(d)
            if isinstance(row, dict) and row.get("report_id") == report_id]


def _registers_binaries(row: Dict[str, Any], binaries: List[Dict[str, Any]]) -> bool:
    """这条 commit 行是否恰好预登记了 ``binaries``（EVAL-1 的 compact_binary 形态，按 JSON
    往返比较，与账本读回的行同形）。"""
    try:
        registered = json.loads(json.dumps(
            [_ledger.compact_binary(b) for b in binaries if isinstance(b, dict)],
            ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError):
        return False  # 不可入账的二元预测不可能被任何 commit 行预登记
    return registered == row.get("binary_forecasts")


def target_meta_for(report_id: str, *, ledger_dir: Optional[str] = None,
                    report_folder: Optional[str] = None,
                    binaries: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """一份报告的预测原点 {as_of, created_at, commit_id, production_primary}。

    - 账本里有它的生产 primary commit 行 → 取该行（as_of_date / created_at / commit_id），
      production_primary=True；
    - 账本（生产或 evaluation）里有它的行、但没有一条是生产 primary（ensemble / what-if /
      comparison / evaluation 类、revision、unpublished_terminal、非生产的旧行）→
      production_primary=False：它的结算绝不能给生产校准打标签（I-21），run_monitor 不写账；
    - 完全没有行（EVAL-1 之前的旧报告、账本关闭）→ {as_of: None, created_at: meta.json 的
      created_at（本地时间→UTC）}，production_primary=None（无从证明，按旧行为结算）。

    给出 ``binaries``（run_monitor 要结算的二元预测）时，只有恰好预登记了它们的 commit 行
    才算数：同一 report_id 若有第二次发布（字节不同的 revision 等），盘上的概率绝不能记在
    primary 的 commit 名下——无匹配的生产 primary → production_primary=False（fail closed）。"""
    rows = _report_ledger_rows(report_id, ledger_dir)
    commits = [row for row in rows if row.get("row_type") == "commit"
               and (binaries is None or _registers_binaries(row, binaries))]
    for row in commits:
        if _is_production_primary(row):
            return _commit_target_meta(row)
    # 旧式 schema_version 1 生产行（无 row_type）不证明任何事，照旧回落 meta.json。
    if any("row_type" in row or not _ledger.is_production_calibration_row(row) for row in rows):
        if commits:
            return _commit_target_meta(commits[0], production_primary=False)
        return {"as_of": None, "created_at": None, "commit_id": None,
                "production_primary": False}
    meta = _read_json(os.path.join(report_folder, "meta.json")) if report_folder else None
    created = meta.get("created_at") if isinstance(meta, dict) else None
    return {"as_of": None, "created_at": _local_stamp_to_utc(created), "commit_id": None,
            "production_primary": None}


# resolutions.jsonl 的基础字段（append_market_resolution 的具名参数）；其余事件字段走 extra。
_EVENT_BASE_KEYS = ("report_id", "forecast_id", "market_id", "resolved_outcome",
                    "resolved_yes_price", "model_p", "market_p_at_research",
                    "brier_contribution", "resolved_at")


def _append_event(event: Dict[str, Any], ledger_dir: Optional[str]) -> Optional[Dict[str, Any]]:
    """把一条结算事件幂等追加进 resolutions.jsonl；重复/失败 → None。"""
    extra = {k: v for k, v in event.items() if k not in _EVENT_BASE_KEYS}
    return _ledger.append_market_resolution(
        report_id=event.get("report_id"), forecast_id=event.get("forecast_id"),
        market_id=event.get("market_id"), resolved_outcome=event.get("resolved_outcome"),
        model_p=event.get("model_p"),
        market_p_at_research=event.get("market_p_at_research"),
        brier_contribution=event.get("brier_contribution"),
        resolved_at=event.get("resolved_at"),
        resolved_yes_price=event.get("resolved_yes_price"),
        d=ledger_dir, extra=extra)


def _fetch_resolutions(client: Any,
                       market_ids: List[str]) -> Tuple[Dict[str, Dict[str, Any]], Set[str]]:
    """查判定终态 → ``(resolutions, answered_ids)``；异常照常上抛由调用方降级。

    客户端提供 fetch_resolutions_answered（PolymarketClient）时，answered 是判定源确实应答过
    的 id（返回了该行，或经单 id 请求确认无此市场）；否则只把返回了数据的 id 视为应答——
    判定源是否确认「无此市场」无从得知，条目宁可保持 pending，也不因失败的批次被永久
    terminal（fail closed）。"""
    fetch_answered = getattr(client, "fetch_resolutions_answered", None)
    if callable(fetch_answered):
        resolutions, answered = fetch_answered(market_ids)
        return dict(resolutions or {}), set(answered or ())
    resolutions = client.fetch_resolutions(market_ids) or {}
    return resolutions, set(resolutions)


def _settlement_counts(settlement: Dict[str, Any], *, appended: int) -> Dict[str, Any]:
    """settle_binaries 的结果 → 结算计数（JSON 摘要与「## Settlement」共用）。"""
    events = settlement.get("events") or []
    return {
        "settled": sum(1 for e in events if e.get("resolution_status") == "settled"),
        "settled_eligible": sum(1 for e in events if e.get("scoring_eligible")),
        "ambiguous": sum(1 for e in events if e.get("resolution_status") == "ambiguous"),
        "terminal": len(settlement.get("terminal") or []),
        "already_terminal": int(settlement.get("already_terminal") or 0),
        "pending_by_reason": dict(settlement.get("pending_by_reason") or {}),
        "ineligible_by_reason": dict(settlement.get("ineligible_by_reason") or {}),
        "appended": appended,
    }


def _skipped_result(report_id: str, reason: str, as_of_day: str,
                    dry_run: bool) -> Dict[str, Any]:
    """闸门未过：零写盘、零网络的结果摘要。"""
    return {
        "report_id": report_id,
        "skipped": reason,
        "as_of": as_of_day,
        "anchored_count": 0,
        "resolved_count": 0,
        "newly_recorded_count": 0,
        "terminal_count": 0,
        "newly_terminal_count": 0,
        "dry_run": bool(dry_run),
        "monitor_report_path": None,
    }


# ---------------------------------------------------------------------------
# 编排：对一份报告跑一次监测
# ---------------------------------------------------------------------------


def run_monitor(report_id: str, *, forecast: Optional[Dict[str, Any]] = None,
                report_folder: Optional[str] = None, client: Any = None,
                ledger_dir: Optional[str] = None, dry_run: bool = False,
                as_of: Optional[str] = None,
                threshold: Optional[float] = None,
                write_report: bool = True,
                publishable_fn: Any = None,
                target_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """对一份报告跑一次解析监测。返回结果摘要 dict（供 CLI 打印/聚合）。

    可注入 forecast / report_folder / client / ledger_dir / as_of，全离线可测。
    dry_run=True 时不写任何盘（price_track / ledger / monitor_report.md 均跳过）。
    任何市场访问失败都退化为部分报告（degraded=True），绝不抛。

    EVAL-2：先过 fail-closed 闸门——``publishable_fn(report_id)``（缺省
    ReportManager.publishable_at_issue）为假 → ``{skipped: 'not_publishable'}``；未注入
    forecast 时只读审计封印的 forecast.json，读不到 → ``{skipped: 'not_sealed'}``；两者
    都不写盘、不联网。``as_of`` 规整为 UTC 的 processed_at（无时区按 UTC 读），是结算判定
    唯一的时钟。``target_meta``（{as_of, created_at, commit_id, production_primary}）缺省取
    target_meta_for（只认恰好预登记了本次二元预测的 commit 行）；production_primary 为
    False（非生产 primary 目标，或盘上二元预测不是 primary 预登记的那份）时结算照算照报、
    事件一律 not_production_primary，但一条也不入账（settlement.not_recorded）。
    terminal 事件照常入账，但不计入 resolved_count / newly_recorded_count /
    resolution_records，单列在 terminal_count / newly_terminal_count 与 settlement 里。"""
    processed_at = normalize_processed_at(as_of or _utcnow_iso())
    as_of_day = processed_at[:10]
    if not _is_publishable(report_id, publishable_fn):
        return _skipped_result(report_id, "not_publishable", as_of_day, dry_run)
    if forecast is None:
        forecast = _load_sealed_forecast(report_id)
        if forecast is None:
            return _skipped_result(report_id, "not_sealed", as_of_day, dry_run)
    thr = threshold if threshold is not None else drift_threshold()
    if report_folder is None:
        report_folder = _report_folder(report_id)
    binaries = [b for b in ((forecast or {}).get("binary_forecasts") or [])
                if isinstance(b, dict)]
    if target_meta is None:
        target_meta = target_meta_for(report_id, ledger_dir=ledger_dir,
                                      report_folder=report_folder, binaries=binaries)
    if client is None:
        from app.utils.prediction_markets import PolymarketClient
        client = PolymarketClient()

    anchored = anchored_forecasts(forecast)
    degraded = False

    # (1)+(2) 重报价锚点市场 → 价格快照；同时收集当前市场访问健康度。
    rows = build_price_rows(anchored)
    requoted: List[Dict[str, Any]] = []
    if rows:
        try:
            requoted = client.requote_markets(rows)
        except Exception as e:  # noqa: BLE001 — 重报价失败退化为部分报告
            logger.warning(f"重报价失败（部分报告）: {e}")
            requoted = []
            degraded = True
        # requote 每行自带 requote_failed；整批全失败也视作 degraded 提示。
        if requoted and all(m.get("requote_failed") for m in requoted):
            degraded = True
    movers = compute_movers(requoted, thr)

    # (3) 判定检查：查询锚点市场终态。
    market_ids = [r["market_id"] for r in rows if r.get("market_id")]
    resolutions: Dict[str, Dict[str, Any]] = {}
    answered: Set[str] = set()
    if market_ids:
        try:
            resolutions, answered = _fetch_resolutions(client, market_ids)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"查询市场判定失败（部分报告）: {e}")
            resolutions, answered = {}, set()
            degraded = True
    if not resolutions and market_ids:
        # 未拿到任何终态（未启用/网络失败）：判定检查这一维退化。
        degraded = True
    resolved_ids = {mid for mid, r in resolutions.items()
                    if isinstance(r, dict) and r.get("resolved")}

    # EVAL-2：结算判定（纯函数）。市场事件 = 已判定 / 50-50 模糊判定；terminal 单列。
    settlement = _settlement.settle_binaries(
        report_id, binaries, resolutions, target_meta=target_meta,
        processed_at=processed_at, min_equivalence=market_min_equivalence(),
        grace_days=pending_grace_days(),
        existing_events=_ledger.read_market_resolutions(ledger_dir),
        answered_market_ids=answered)
    records = [e for e in settlement["events"] if e.get("resolution_status") == "settled"]
    # 非生产 primary 目标（ensemble / what-if / comparison / revision / evaluation）：结算
    # 照算照报，但一条也不写进生产 resolutions.jsonl（I-21；键先写者赢，写错无法更正）。
    record_settlement = (target_meta or {}).get("production_primary") is not False

    # (4) 指标检查：过期却无市场判定的预测 → 需人工判定。
    needs_manual = detect_needs_manual(binaries, resolved_ids, as_of_day)

    # ── 写盘（dry-run 跳过全部写操作）──
    newly_recorded: List[Dict[str, Any]] = []
    newly_terminal: List[Dict[str, Any]] = []
    appended = 0
    if not dry_run:
        if requoted:
            append_price_snapshot(report_folder,
                                  _price_snapshot(report_id, processed_at, requoted))
    if not dry_run and record_settlement:
        for event in settlement["events"]:
            written = _append_event(event, ledger_dir)
            if written is None:
                continue
            appended += 1
            if written.get("resolution_status") == "settled":
                newly_recorded.append(written)
        for event in settlement["terminal"]:
            written = _append_event(event, ledger_dir)
            if written is not None:
                appended += 1
                newly_terminal.append(written)
    settlement_summary = _settlement_counts(settlement, appended=appended)
    if not record_settlement:
        settlement_summary["not_recorded"] = _settlement.NOT_PRODUCTION_PRIMARY

    # ── 汇总分数（账本读取；dry-run 也能读，只是不含本次未写入的新判定）──
    calibration = _ledger.calibration_summary(ledger_dir)
    market_brier = _ledger.market_brier_summary(ledger_dir)

    md = render_monitor_md(
        report_id=report_id, as_of=as_of_day, movers=movers,
        resolution_records=records, needs_manual=needs_manual,
        calibration=calibration, market_brier=market_brier,
        anchored_count=len(anchored), degraded=degraded,
        settlement=settlement_summary,
        settlement_events=settlement["events"] + settlement["terminal"])

    report_path: Optional[str] = None
    if not dry_run and write_report:
        try:
            from app.utils.atomic import write_text_atomic
            report_path = os.path.join(report_folder, "monitor_report.md")
            write_text_atomic(report_path, md)
        except Exception as e:  # noqa: BLE001 — 落 md 失败不影响返回摘要
            logger.warning(f"落 monitor_report.md 失败（忽略）: {e}")
            report_path = None

    return {
        "report_id": report_id,
        "as_of": as_of_day,
        "processed_at": processed_at,
        "anchored_count": len(anchored),
        "movers": movers,
        "resolved_count": len(records),
        "newly_recorded_count": len(newly_recorded),
        "terminal_count": len(settlement["terminal"]),
        "newly_terminal_count": len(newly_terminal),
        "needs_manual_count": len(needs_manual),
        "needs_manual": needs_manual,
        "resolution_records": records,
        "settlement": settlement_summary,
        "calibration": calibration,
        "market_brier": market_brier,
        "degraded": degraded,
        "dry_run": bool(dry_run),
        "monitor_report_path": report_path,
        "monitor_report_md": md,
    }


# ---------------------------------------------------------------------------
# EVAL-2：账本结算扫描（settle 子命令；run --all-recent 在 RESOLUTION_SETTLE_LEDGER 下也跑）
# ---------------------------------------------------------------------------


def settle_targets(entries: List[Dict[str, Any]], limit: int,
                   existing: Optional[List[Dict[str, Any]]] = None, *,
                   processed_at: str, grace_days: int
                   ) -> Tuple[List[Tuple[Dict[str, Any], List[Dict[str, Any]]]], int]:
    """本轮结算扫描的目标 → ``([(commit 行, 本轮可处理的二元预测)], deferred_by_cap)``。

    commit 行只在报告发布封印后写入，且自带 binary_forecasts，报告目录已删也能结算。
    ensemble / evaluation 等非生产类、revision 与 unpublished_terminal 行一律不扫。
    每行只取 processed_at 时刻可处理的条目（forecast_resolution.due_binaries：未入账、且
    有市场锚点，或无锚点且已过 grace）；无可处理条目的行不占上限——grace 内的无锚点条目
    本轮无事可做，若占上限，更老目标的 grace terminal 就永远轮不到。
    上限 limit 只限需联网查判定的行（含未入账锚定条目），先排「逾期」行：有锚定条目的
    结算判定日（settlement_resolution_date）已早于处理日——这些市场本该已收盘，其
    grace terminal 也要先联网确认；逾期行按最早逾期日、再按账本先后（老的在前）排，其余
    行新到旧。否则长期未收盘的新目标会一直占满上限，老目标永远查不到、也永远结不了。
    超限的行 deferred_by_cap 计数，其锚定条目留待下轮；它们已过 grace 的无锚点条目照常
    结算——terminal 不需要网络。"""
    recorded = _settlement.recorded_items(existing)
    cap = max(0, int(limit))
    overdue: List[Tuple[str, int, Dict[str, Any], List[Dict[str, Any]]]] = []
    current: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
    for position, row in enumerate(entries):
        if not _is_production_primary(row) or not str(row.get("report_id") or "").strip():
            continue
        due = _settlement.due_binaries(row.get("report_id"), row.get("binary_forecasts"),
                                       recorded, processed_at=processed_at,
                                       grace_days=grace_days)
        if not due:
            continue
        since = _settlement.overdue_since(due, processed_at)
        if since:
            overdue.append((since, position, row, due))
        else:
            current.append((row, due))
    ordered = [(row, due) for _since, _position, row, due in sorted(
        overdue, key=lambda item: (item[0], item[1]))] + current[::-1]
    targets: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
    fetching = deferred = 0
    for row, due in ordered:
        if any(_settlement.anchor_market_id(b) for b in due):
            if fetching < cap:
                fetching += 1
                targets.append((row, due))
                continue
            deferred += 1
            due = [b for b in due if not _settlement.anchor_market_id(b)]
        if due:
            targets.append((row, due))
    return targets, deferred


def _merge_counts(total: Dict[str, int], part: Dict[str, Any]) -> None:
    for reason, n in (part or {}).items():
        total[reason] = total.get(reason, 0) + int(n)


def settle_ledger(*, client: Any = None, ledger_dir: Optional[str] = None,
                  dry_run: bool = False, as_of: Optional[str] = None,
                  max_targets: Optional[int] = None) -> Dict[str, Any]:
    """扫描账本 primary commit 行，一次批量查判定，把结算事件幂等追加进 resolutions.jsonl。

    返回计数 {targets, deferred_by_cap, settled, settled_eligible, ambiguous, terminal,
    already_terminal, pending_by_reason, ineligible_by_reason, appended, errors, degraded,
    dry_run, as_of}，
    只计本轮可处理的条目（见 settle_targets）。dry_run 不写盘；重跑只会命中幂等键、不重复
    追加；判定源不可达只产生 pending（degraded=True）；单行坏数据记日志、计入 errors 并跳过。"""
    processed_at = normalize_processed_at(as_of or _utcnow_iso())
    limit = settle_max_targets() if max_targets is None else max(1, int(max_targets))
    grace_days = pending_grace_days()
    existing = _ledger.read_market_resolutions(ledger_dir)
    targets, deferred = settle_targets(_ledger.read_ledger(ledger_dir), limit, existing,
                                       processed_at=processed_at, grace_days=grace_days)
    market_ids: List[str] = []
    for _row, due in targets:
        for b in due:
            mid = _settlement.anchor_market_id(b)
            if mid and mid not in market_ids:
                market_ids.append(mid)
    resolutions: Dict[str, Dict[str, Any]] = {}
    answered: Set[str] = set()
    degraded = False
    if market_ids:
        if client is None:
            from app.utils.prediction_markets import PolymarketClient
            client = PolymarketClient()
        try:
            resolutions, answered = _fetch_resolutions(client, market_ids)
        except Exception as e:  # noqa: BLE001 — 判定源失败只让条目保持 pending
            logger.warning(f"结算扫描查询判定失败（条目保持 pending）: {e}")
            resolutions, answered = {}, set()
        degraded = not resolutions
    totals: Dict[str, Any] = {"settled": 0, "settled_eligible": 0, "ambiguous": 0,
                              "terminal": 0, "already_terminal": 0, "appended": 0}
    pending: Dict[str, int] = {}
    ineligible: Dict[str, int] = {}
    errors = 0
    for row, due in targets:
        try:
            out = _settlement.settle_binaries(
                row.get("report_id"), due, resolutions,
                target_meta=_commit_target_meta(row), processed_at=processed_at,
                min_equivalence=market_min_equivalence(), grace_days=grace_days,
                existing_events=existing, answered_market_ids=answered)
            appended = 0
            if not dry_run:
                appended = sum(1 for event in out["events"] + out["terminal"]
                               if _append_event(event, ledger_dir) is not None)
        except Exception as e:  # noqa: BLE001 — 一行坏数据不应中断整轮扫描
            logger.error(f"结算账本行失败（跳过）: {row.get('report_id')}: {e}", exc_info=True)
            errors += 1
            continue
        counts = _settlement_counts(out, appended=appended)
        for key in totals:
            totals[key] += counts[key]
        _merge_counts(pending, counts["pending_by_reason"])
        _merge_counts(ineligible, counts["ineligible_by_reason"])
    return {
        "targets": len(targets),
        "deferred_by_cap": deferred,
        **totals,
        "pending_by_reason": dict(sorted(pending.items())),
        "ineligible_by_reason": dict(sorted(ineligible.items())),
        "errors": errors,
        "degraded": degraded,
        "dry_run": bool(dry_run),
        "as_of": processed_at,
    }


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _summary_row(res: Dict[str, Any]) -> Dict[str, Any]:
    """把 run_monitor 的完整结果压成一行便于聚合打印（去掉大字段）。"""
    if res.get("skipped"):
        return {"report_id": res.get("report_id"), "skipped": res.get("skipped")}
    settlement = res.get("settlement") or {}
    return {
        "report_id": res.get("report_id"),
        "anchored": res.get("anchored_count"),
        "movers": len(res.get("movers") or []),
        "resolved": res.get("resolved_count"),
        "newly_recorded": res.get("newly_recorded_count"),
        "settled_eligible": settlement.get("settled_eligible"),
        "ambiguous": settlement.get("ambiguous"),
        "terminal": res.get("terminal_count"),
        "newly_terminal": res.get("newly_terminal_count"),
        "pending_by_reason": settlement.get("pending_by_reason"),
        "ineligible_by_reason": settlement.get("ineligible_by_reason"),
        "needs_manual": res.get("needs_manual_count"),
        "degraded": res.get("degraded"),
        "monitor_report": res.get("monitor_report_path"),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="resolution_monitor.py",
        description="MON-1 解析追踪 / 持续预测监测（cron 驱动；对锚定预测重报价+查判定，落账本与 monitor_report.md）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("run", help="监测一份报告，或用 --all-recent 批量监测最近报告")
    sp.add_argument("report_id", nargs="?", default=None,
                    help="报告 id 或管线 id（与 --all-recent 二选一）")
    sp.add_argument("--all-recent", nargs="?", type=int, const=-1, default=None,
                    metavar="N", help="监测最近 N 份报告（缺省 N=RESOLUTION_MONITOR_RECENT_N）")
    sp.add_argument("--dry-run", action="store_true", help="只观测不写盘（无 price_track/账本/monitor_report.md）")

    ss = sub.add_parser("settle", help="EVAL-2：扫描账本生产 primary commit 行，追加结算事件（resolutions.jsonl）")
    ss.add_argument("--dry-run", action="store_true", help="只计算结算计数，不写账本")

    sub.add_parser("summary", help="打印账本里的持续 Brier / 校准（无网络）")

    return p


def _cmd_run(args: argparse.Namespace) -> int:
    dry = bool(args.dry_run)
    # 目标报告集合：--all-recent 优先；否则单个 report_id/pipeline_id。
    if args.all_recent is not None:
        n = recent_n_default() if args.all_recent in (None, -1) else max(1, int(args.all_recent))
        report_ids = recent_report_ids(n)
        if not report_ids:
            print("未找到可监测的最近报告。", file=sys.stderr)
            # EVAL-2：commit 行自包含，报告目录已删也要照常结算账本。
            if not settle_ledger_enabled():
                return 1
    elif args.report_id:
        rid = resolve_report_id(args.report_id)
        if not rid:
            print(f"未找到报告/管线: {args.report_id}", file=sys.stderr)
            return 1
        report_ids = [rid]
    else:
        print("需给出 report_id 或 --all-recent。", file=sys.stderr)
        return 2

    results: List[Dict[str, Any]] = []
    for rid in report_ids:
        try:
            res = run_monitor(rid, dry_run=dry)
        except Exception as e:  # noqa: BLE001 — 单份失败不应中断整批
            logger.error(f"监测报告 {rid} 失败（跳过）: {e}", exc_info=True)
            results.append({"report_id": rid, "error": str(e)})
            continue
        results.append(res)

    payload: Dict[str, Any] = {
        "dry_run": dry,
        "count": len(results),
        "reports": [_summary_row(r) if "error" not in r else r for r in results],
    }
    # EVAL-2：批量监测后顺带扫一遍账本 primary commit 行（失败只记日志，不影响本轮结果）。
    if args.all_recent is not None and settle_ledger_enabled():
        try:
            payload["settlement"] = settle_ledger(dry_run=dry)
        except Exception as e:  # noqa: BLE001 — 结算扫描是增强，绝不打断监测
            logger.error(f"账本结算扫描失败（跳过）: {e}", exc_info=True)
            payload["settlement"] = {"error": str(e)}
    _print_json(payload)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "run":
        return _cmd_run(args)
    if args.cmd == "settle":
        _print_json(settle_ledger(dry_run=bool(args.dry_run)))
        return 0
    if args.cmd == "summary":
        _print_json({
            "market_brier": _ledger.market_brier_summary(),
            "scenario_calibration": _ledger.calibration_summary(),
        })
        return 0
    return 2  # 不可达（subparser required）


if __name__ == "__main__":
    raise SystemExit(main())
