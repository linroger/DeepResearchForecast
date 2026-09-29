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
   需人工判定清单、以及账本里的持续 Brier / 校准。

设计与 scripts/scheduled_rerun.py 同构：脚本自撑 sys.path、Config 旋钮经 getattr 读取
（本文件不拥有 config.py）、全链路 degrade-safe——任何网络失败只产出**部分**报告，
绝不抛异常、绝不改动任何在线管线语义。``--dry-run`` 全程不写盘（纯观测）。

命令行
------
    python scripts/resolution_monitor.py run <report_id|pipeline_id> [--dry-run]
    python scripts/resolution_monitor.py run --all-recent [N] [--dry-run]   # 最近 N 份报告（缺省 N=RESOLUTION_MONITOR_RECENT_N）
    python scripts/resolution_monitor.py summary                            # 只打印账本里的持续 Brier / 校准（无网络）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ── 让脚本无论从哪个 cwd 调用都能 import 到 backend 的 app 包（与 scheduled_rerun.py 一致）──
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.config import Config  # noqa: E402
from app.services import forecast_ledger as _ledger  # noqa: E402
from app.utils.logger import get_logger  # noqa: E402

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


# EVAL-13: exclude_evaluation 时按 n 的这个倍数多取候选，剔除评估运行报告后仍能凑满 n 份。
EVALUATION_OVERFETCH_FACTOR = 4
# EVAL-13: 归属回退（模拟 id → 是否属评估运行）的进程内备忘，recent_report_ids 与 run_monitor
# 共用：一轮 `run --all-recent` 对每个模拟只扫一次管线状态，而不是每份报告扫两次。监测以一次性
# CLI 子进程运行（resolution_autorun 每轮新起进程），recent_report_ids 每批从空备忘开始；
# 查找失败（fail closed）的答案从不入备忘，下次仍重查。
_EVALUATION_OWNER_MEMO: Dict[str, bool] = {}


def is_evaluation_forecast(forecast: Any) -> bool:
    """EVAL-13: True for the forecast of an evaluation run (``evaluation.record_class``)."""
    if not isinstance(forecast, dict):
        return False
    stamp = forecast.get("evaluation")
    return isinstance(stamp, dict) and stamp.get("record_class") == "evaluation"


def _report_owned_by_evaluation_run(report_folder: Optional[str],
                                    memo: Optional[Dict[str, bool]] = None) -> bool:
    """EVAL-13 fail-closed fallback for a report whose forecast carries no evaluation stamp.

    The stamp rides on forecast.json, so an evaluation report that never reached a
    stamped write (no forecast spine and a failed finalize) carries none. Its
    meta.json still names the simulation, and the pipeline that ran it decides
    (``evaluation_context_for_simulation``: its pin, its own admission marker, or a
    fail-closed context when that lookup fails). A lookup that cannot even be
    imported excludes the report too. ``memo`` caches the answer per simulation id;
    a lookup that failed is never cached.
    """
    meta = _read_json(os.path.join(report_folder, "meta.json")) if report_folder else None
    simulation_id = str(meta.get("simulation_id") or "").strip() if isinstance(meta, dict) else ""
    if not simulation_id:
        return False
    if memo is not None and simulation_id in memo:
        return memo[simulation_id]
    try:
        from app.services.pipeline_orchestrator import evaluation_context_for_simulation
        context = evaluation_context_for_simulation(simulation_id)
    except Exception as e:  # noqa: BLE001 — 归属无法判定 → 按评估运行跳过（fail closed）
        logger.warning(f"模拟 {simulation_id} 的评估运行归属无法判定（按评估运行跳过）: {e}")
        return True
    if isinstance(context, dict) and context.get("lookup_failed") is True:
        return True
    owned = context is not None
    if memo is not None:
        memo[simulation_id] = owned
    return owned


def _is_evaluation_report(report_id: str, memo: Optional[Dict[str, bool]] = None) -> bool:
    """EVAL-13: whether a report belongs to an evaluation run.

    Reads the report's forecast.json, the file run_monitor processes: a sealed
    forecast is exactly these bytes, so an unsealed or stale-policy evaluation
    report is recognised too. A forecast without the stamp (or no forecast.json)
    falls back to the run that owns the report's simulation (fail closed).
    """
    try:
        folder = _report_folder(report_id)
    except Exception:  # noqa: BLE001 — 不可定位的报告交由 run_monitor 自身降级
        return False
    return (is_evaluation_forecast(_read_json(os.path.join(folder, "forecast.json")))
            or _report_owned_by_evaluation_run(folder, memo))


def recent_report_ids(n: int, *, as_of: Optional[str] = None,
                      exclude_evaluation: bool = True) -> List[str]:
    """最近 n 份报告的 report_id（按 created_at 倒序，与 ReportManager.list_reports 同序）。
    RESOLUTION_MONITOR_LOOKBACK_DAYS>0 时进一步过滤到 created_at 在近 N 天内的报告。

    EVAL-13 ``exclude_evaluation``（默认开）：评估运行的报告（forecast.evaluation.record_class
    == 'evaluation'；无此章时按报告模拟所属管线判定，fail closed）绝不进入监测；多取至多
    4n 份候选，剔除后仍返回至多 n 份生产报告。没有评估报告时结果与旧行为逐字节一致。"""
    wanted = max(1, int(n))
    limit = wanted * EVALUATION_OVERFETCH_FACTOR if exclude_evaluation else wanted
    try:
        from app.services.report_agent import ReportManager
        reports = ReportManager.list_reports(limit=limit)
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
    _EVALUATION_OWNER_MEMO.clear()
    for r in reports:
        if len(out) >= wanted:
            break
        if cutoff is not None and str(getattr(r, "created_at", "") or "")[:10] < cutoff:
            continue
        rid = getattr(r, "report_id", None)
        if not rid:
            continue
        if exclude_evaluation and _is_evaluation_report(str(rid), _EVALUATION_OWNER_MEMO):
            continue
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
    """对每条锚定预测：若其锚点市场已判定且能定二元真值，回算 Brier 并组装一条判定记录。

    y（真值）取自市场终态：resolved_yes_price ≥ 0.5 ⇒ 事件发生（y=1），否则 y=0。
    model_p = 该二元预测概率；brier_contribution = (model_p − y)²。纯函数、可离线单测。
    无法定真值（缺 resolved_yes_price）或未判定 → 跳过（unknown，不硬造标签）。"""
    records: List[Dict[str, Any]] = []
    for b in anchored:
        anchor = b.get("market_anchor") or {}
        mid = str(anchor.get("market_id") or "").strip()
        res = resolutions.get(mid) if mid else None
        if not isinstance(res, dict) or not res.get("resolved"):
            continue
        yes_price = _coerce_float(res.get("resolved_yes_price"))
        if yes_price is None:
            continue  # 已关闭但真值不可定 → 交给「需人工判定」，不入 Brier
        y = 1.0 if yes_price >= 0.5 else 0.0
        model_p = _coerce_float(b.get("probability"))
        market_p = _coerce_float(anchor.get("price_at_research"))
        if market_p is None:
            market_p = _coerce_float(anchor.get("implied_yes_prob"))
        brier = round((model_p - y) ** 2, 4) if model_p is not None else None
        records.append({
            "report_id": report_id,
            "forecast_id": b.get("id"),
            "market_id": mid,
            "resolved_outcome": res.get("resolved_outcome"),
            "resolved_yes_price": round(yes_price, 4),
            "model_p": model_p,
            "market_p_at_research": market_p,
            "brier_contribution": brier,
            "resolved_at": resolved_at,
        })
    return records


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


def render_monitor_md(*, report_id: str, as_of: str,
                      movers: List[Dict[str, Any]],
                      resolution_records: List[Dict[str, Any]],
                      needs_manual: List[Dict[str, Any]],
                      calibration: Dict[str, Any],
                      market_brier: Dict[str, Any],
                      anchored_count: int,
                      degraded: bool) -> str:
    """把一次监测结果渲染成确定性 markdown（无 LLM）。空信号也产出可读骨架。"""
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
# 编排：对一份报告跑一次监测
# ---------------------------------------------------------------------------


def run_monitor(report_id: str, *, forecast: Optional[Dict[str, Any]] = None,
                report_folder: Optional[str] = None, client: Any = None,
                ledger_dir: Optional[str] = None, dry_run: bool = False,
                as_of: Optional[str] = None,
                threshold: Optional[float] = None,
                write_report: bool = True) -> Dict[str, Any]:
    """对一份报告跑一次解析监测。返回结果摘要 dict（供 CLI 打印/聚合）。

    可注入 forecast / report_folder / client / ledger_dir / as_of，全离线可测。
    dry_run=True 时不写任何盘（price_track / ledger / monitor_report.md 均跳过）。
    任何市场访问失败都退化为部分报告（degraded=True），绝不抛。
    EVAL-13：评估运行的预测（forecast.evaluation.record_class == 'evaluation'，或无此章而
    报告模拟属于评估运行）直接返回 ``skipped='evaluation_run'`` 的零计数摘要，零写盘、
    零市场访问。"""
    as_of = as_of or _utcnow_iso()
    as_of_day = str(as_of)[:10]
    thr = threshold if threshold is not None else drift_threshold()
    if report_folder is None:
        report_folder = _report_folder(report_id)
    if forecast is None:
        forecast = _read_json(os.path.join(report_folder, "forecast.json"))
    if (is_evaluation_forecast(forecast)
            or _report_owned_by_evaluation_run(report_folder, _EVALUATION_OWNER_MEMO)):
        # EVAL-13：评估运行的预测绝不被监测——不重报价、不入账、不落任何文件。
        return {
            "report_id": report_id, "as_of": as_of_day, "anchored_count": 0, "movers": [],
            "resolved_count": 0, "newly_recorded_count": 0, "needs_manual_count": 0,
            "needs_manual": [], "resolution_records": [], "calibration": {},
            "market_brier": {}, "degraded": False, "dry_run": bool(dry_run),
            "monitor_report_path": None, "monitor_report_md": "",
            "skipped": "evaluation_run",
        }
    if client is None:
        from app.utils.prediction_markets import PolymarketClient
        client = PolymarketClient()

    binaries = [b for b in ((forecast or {}).get("binary_forecasts") or [])
                if isinstance(b, dict)]
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
    if market_ids:
        try:
            resolutions = client.fetch_resolutions(market_ids) or {}
        except Exception as e:  # noqa: BLE001
            logger.warning(f"查询市场判定失败（部分报告）: {e}")
            resolutions = {}
            degraded = True
    if not resolutions and market_ids:
        # 未拿到任何终态（未启用/网络失败）：判定检查这一维退化。
        degraded = True
    resolved_ids = {mid for mid, r in resolutions.items()
                    if isinstance(r, dict) and r.get("resolved")}

    records = build_resolution_records(anchored, resolutions,
                                       report_id=report_id, resolved_at=as_of)

    # (4) 指标检查：过期却无市场判定的预测 → 需人工判定。
    needs_manual = detect_needs_manual(binaries, resolved_ids, as_of_day)

    # ── 写盘（dry-run 跳过全部写操作）──
    newly_recorded: List[Dict[str, Any]] = []
    if not dry_run:
        if requoted:
            append_price_snapshot(report_folder,
                                  _price_snapshot(report_id, as_of, requoted))
        for rec in records:
            written = _ledger.append_market_resolution(
                report_id=rec["report_id"], forecast_id=rec["forecast_id"],
                market_id=rec["market_id"], resolved_outcome=rec.get("resolved_outcome"),
                model_p=rec.get("model_p"),
                market_p_at_research=rec.get("market_p_at_research"),
                brier_contribution=rec.get("brier_contribution"),
                resolved_at=rec.get("resolved_at"),
                resolved_yes_price=rec.get("resolved_yes_price"),
                d=ledger_dir)
            if written is not None:
                newly_recorded.append(written)

    # ── 汇总分数（账本读取；dry-run 也能读，只是不含本次未写入的新判定）──
    calibration = _ledger.calibration_summary(ledger_dir)
    market_brier = _ledger.market_brier_summary(ledger_dir)

    md = render_monitor_md(
        report_id=report_id, as_of=as_of_day, movers=movers,
        resolution_records=records, needs_manual=needs_manual,
        calibration=calibration, market_brier=market_brier,
        anchored_count=len(anchored), degraded=degraded)

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
        "anchored_count": len(anchored),
        "movers": movers,
        "resolved_count": len(records),
        "newly_recorded_count": len(newly_recorded),
        "needs_manual_count": len(needs_manual),
        "needs_manual": needs_manual,
        "resolution_records": records,
        "calibration": calibration,
        "market_brier": market_brier,
        "degraded": degraded,
        "dry_run": bool(dry_run),
        "monitor_report_path": report_path,
        "monitor_report_md": md,
    }


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _summary_row(res: Dict[str, Any]) -> Dict[str, Any]:
    """把 run_monitor 的完整结果压成一行便于聚合打印（去掉大字段）。"""
    return {
        "report_id": res.get("report_id"),
        "anchored": res.get("anchored_count"),
        "movers": len(res.get("movers") or []),
        "resolved": res.get("resolved_count"),
        "newly_recorded": res.get("newly_recorded_count"),
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

    _print_json({
        "dry_run": dry,
        "count": len(results),
        "reports": [_summary_row(r) if "error" not in r else r for r in results],
    })
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "run":
        return _cmd_run(args)
    if args.cmd == "summary":
        _print_json({
            "market_brier": _ledger.market_brier_summary(),
            "scenario_calibration": _ledger.calibration_summary(),
        })
        return 0
    return 2  # 不可达（subparser required）


if __name__ == "__main__":
    raise SystemExit(main())
