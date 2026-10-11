"""NEXTSTEPS P2-4: a forecast ledger that finally closes the calibration loop.

A forecaster that never learns whether its 70%s happen 70% of the time is
calibration-*capable*, not calibrated. Every ``forecast.json`` is appended here keyed
by horizon/resolution date; once outcomes are resolved (via the ``/api/v1/resolve``
endpoint or the ``forecast_tools backtest`` CLI), ``backtest.calibration_report`` over
the ledger yields historical Brier / calibration-error — which is surfaced into NEW
forecasts' ``confidence_rationale`` so confidence becomes *earned*, not self-asserted.

jsonl append/read (+ atomic rewrite for resolution) → pure enough to unit-test offline.
``scripts/scheduled_rerun.py`` can use ``due_for_resolution`` to detect forecasts whose
horizon/indicator dates have passed and queue them.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, List, Optional


def ledger_dir() -> str:
    """Resolve the ledger directory (FORECAST_LEDGER_DIR, else under PIPELINE_DATA_DIR)."""
    try:
        from ..config import Config
        d = getattr(Config, "FORECAST_LEDGER_DIR", "") or os.path.join(
            getattr(Config, "PIPELINE_DATA_DIR", "uploads/pipelines"), "_forecast_ledger")
    except Exception:  # noqa: BLE001
        d = os.path.join("uploads/pipelines", "_forecast_ledger")
    return d


def _ledger_file(d: Optional[str] = None) -> str:
    return os.path.join(d or ledger_dir(), "ledger.jsonl")


def evaluation_ledger_dir() -> str:
    """Foglamp WP1 (1E, I-20/I-21): the isolated EVALUATION ledger directory.

    Golden/characterization rows accumulate here — physically separate from the
    production ledger so evaluation outcomes can never leak into production
    calibration, recalibration, or earned-confidence numbers.
    """
    return os.path.join(os.path.dirname(ledger_dir().rstrip(os.sep)) or ".",
                        "_evaluation_ledger")


def is_production_calibration_row(e: Dict[str, Any]) -> bool:
    """Foglamp WP1 (1E, I-21): True only for rows eligible for PRODUCTION calibration.

    Excludes golden-question rows (``golden: true``), rows explicitly marked
    ``characterization_only``, and rows whose ``record_class`` is ``evaluation``
    — enforced here by record type, not by caller convention, so historical
    mixed-ledger files stop contaminating production numbers.
    """
    if not isinstance(e, dict):
        return False
    if e.get("golden") or e.get("characterization_only"):
        return False
    if str(e.get("record_class") or "").strip().lower() == "evaluation":
        return False
    return True


def append_forecast(forecast: Optional[Dict[str, Any]], *, report_id: str,
                    horizon: Optional[str] = None, resolution_date: Optional[str] = None,
                    created_at: Optional[str] = None, d: Optional[str] = None,
                    objective_signals: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Append one forecast entry to the ledger (jsonl). Best-effort → None on failure.

    Stores only what scoring needs (scenario names + probabilities) + keys for the
    resolution scheduler. ``resolution_date`` defaults to the horizon (year-end).

    EVAL-1 / GAP-4: an optional ``objective_signals`` dict (free, deterministic report
    quality metrics — citation coverage, sharp-criteria ratio, etc.) is persisted
    alongside the entry when supplied, so the ledger doubles as an evaluation log even
    before outcomes resolve. Default None → entry shape unchanged (degrade-safe).
    """
    if not isinstance(forecast, dict):
        return None
    scenarios = [
        {"name": s.get("name"), "probability": s.get("probability"),
         "resolution_criteria": s.get("resolution_criteria")}
        for s in (forecast.get("scenarios") or []) if isinstance(s, dict)
    ]
    if not scenarios:
        return None
    hz = horizon or str(forecast.get("horizon") or "").strip() or None
    entry = {
        "report_id": report_id,
        "horizon": hz,
        "resolution_date": resolution_date or _year_end(hz),
        "created_at": created_at,
        "scenarios": scenarios,
        "confidence": forecast.get("confidence"),
        "resolved": False,
        "outcome": None,
        "schema_version": 1,
    }
    if isinstance(objective_signals, dict) and objective_signals:
        entry["objective_signals"] = objective_signals
    try:
        target = _ledger_file(d)
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry
    except OSError:
        return None


def append_golden_result(*, question_id: str, probability: Any, resolved_outcome: bool,
                         question: Optional[str] = None, category: Optional[str] = None,
                         resolution_date: Optional[str] = None, as_of_date: Optional[str] = None,
                         resolution_criteria: Optional[str] = None,
                         report_id: Optional[str] = None, d: Optional[str] = None,
                         objective_signals: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """EVAL-1: append ONE already-resolved golden binary question to the ledger.

    黄金题是「已判定」的二元(YES/NO)问题；把它建模成两情景（YES=p、NO=1-p）的 *已解析*
    预测写入同一账本，于是既有校准机器（``calibration_summary`` → ``backtest.calibration_report``，
    以及 ``report_visualizer`` 渲染的校准曲线）会把黄金题结局与真实流水线预测一并累积——
    这正是把「预测好不好」变成可累加数字所需的闭环。

    与 ``append_forecast`` 的差异（故意各自独立，绝不改后者契约）：本函数写入 ``resolved=True``
    且直接带 ``outcome``（'YES' 或 'NO'），因为黄金题的真实结局本就已知。``probability`` 为
    模型给出的 YES 概率 [0,1]；非法概率钳到 [0,1]（缺失/无法解析 → None → 跳过，绝不污染账本）。
    Best-effort → 失败或输入非法时返回 None（degrade-safe）。

    ``golden=True`` + ``question_id`` 提供溯源，便于日后从账本里挑出/剔除黄金题条目。
    """
    try:
        p = float(probability)
    except (TypeError, ValueError):
        return None
    if p != p or p in (float("inf"), float("-inf")):  # NaN/inf → 拒收
        return None
    p = max(0.0, min(1.0, p))
    qid = str(question_id or "").strip()
    if not qid:
        return None
    outcome = "YES" if resolved_outcome else "NO"
    scenarios = [
        {"name": "YES", "probability": round(p, 4), "resolution_criteria": str(resolution_criteria or "")},
        {"name": "NO", "probability": round(1.0 - p, 4), "resolution_criteria": str(resolution_criteria or "")},
    ]
    entry = {
        "report_id": report_id or f"golden:{qid}",
        "horizon": None,
        "resolution_date": resolution_date,
        "created_at": as_of_date,
        "scenarios": scenarios,
        "confidence": None,
        "resolved": True,
        "outcome": outcome,
        "schema_version": 1,
        # 溯源：把黄金题条目标记出来，供筛选/剔除；不参与评分逻辑。
        "golden": True,
        "question_id": qid,
        "category": category,
        "question": question,
        "as_of_date": as_of_date,
        # Foglamp WP1 (1E, I-20/I-21)：记录类型强制标注——黄金题是含答案的历史
        # 回溯特征化数据，永不参与生产校准/重校准/晋升。
        "record_class": "evaluation",
        "characterization_only": True,
    }
    if isinstance(objective_signals, dict) and objective_signals:
        entry["objective_signals"] = objective_signals
    try:
        # Foglamp WP1 (1E)：黄金题写入被路由到隔离的评估账本。目标目录解析为生产
        # 账本目录（显式传入或默认）时一律改写到 evaluation_ledger_dir()，绝不落进
        # 生产 ledger.jsonl —— 生产读侧的 is_production_calibration_row 是第二道防线。
        _target_dir = os.path.abspath(d) if d else os.path.abspath(ledger_dir())
        if _target_dir == os.path.abspath(ledger_dir()):
            _target_dir = evaluation_ledger_dir()
            entry["ledger_redirected"] = "evaluation"
        target = _ledger_file(_target_dir)
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry
    except OSError:
        return None


def _year_end(horizon: Optional[str]) -> Optional[str]:
    """A free-text horizon like '2030' → '2030-12-31' (resolution date proxy).

    现为 ``sim_timeline.extract_horizon`` 的薄封装（签名不变，消灭重复的年份正则）：
    富文本期限（"mid-2027"/"2027年底"）解析到真实判定日而非一律年底。as_of 锚点取
    文本中最早年份的前一年（账本可能补录已过期的 horizon，判定日在过去也须解析出来，
    供 due_for_resolution 追缴）；无年份时退回今天。解析不出 → None（旧行为）。
    """
    if not horizon:
        return None
    try:
        from datetime import date

        from ..utils import sim_timeline

        text = str(horizon)
        years = [int(y) for y in sim_timeline._TIER4.findall(text)]
        as_of = date(min(years) - 1, 1, 1) if years else date.today()
        res = sim_timeline.extract_horizon(text, as_of)
        return res.horizon_date if res else None
    except Exception:  # noqa: BLE001 — 判定日推导为 best-effort，绝不阻断入账
        return None


def read_ledger(d: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read all ledger entries (tolerates corrupt/half-written tail lines)."""
    out: List[Dict[str, Any]] = []
    path = _ledger_file(d)
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


def calibration_summary(d: Optional[str] = None, entries: Optional[List[Dict[str, Any]]] = None,
                        *, include_evaluation: bool = False) -> Dict[str, Any]:
    """Historical calibration over RESOLVED ledger entries (Brier / ECE / count).

    Each resolved entry carries ``outcome`` = the scenario name that actually occurred.
    Returns ``{n_resolved, mean_brier, calibration_error}`` (Nones when nothing resolved).

    Foglamp WP1 (1E, I-21): by default only PRODUCTION rows count —
    golden/characterization/evaluation rows are excluded by record type. The
    evaluation lane (``golden_eval``) may opt in with ``include_evaluation=True``
    to score an isolated evaluation ledger; production callers never pass it.
    """
    led = entries if entries is not None else read_ledger(d)
    resolved = [
        {"forecast": {"scenarios": e.get("scenarios")}, "outcome": e.get("outcome")}
        for e in led
        if e.get("resolved") and e.get("outcome") and e.get("scenarios")
        and (include_evaluation or is_production_calibration_row(e))
    ]
    if not resolved:
        return {"n_resolved": 0, "mean_brier": None, "calibration_error": None}
    try:
        from .backtest import calibration_report
        rep = calibration_report(resolved)
        return {"n_resolved": len(resolved),
                "mean_brier": rep.get("mean_brier"),
                "calibration_error": rep.get("calibration_error")}
    except Exception:  # noqa: BLE001
        return {"n_resolved": len(resolved), "mean_brier": None, "calibration_error": None}


def due_for_resolution(as_of: str, d: Optional[str] = None) -> List[Dict[str, Any]]:
    """Unresolved entries whose resolution_date has passed (≤ as_of). For the scheduler."""
    led = read_ledger(d)
    out = []
    for e in led:
        if e.get("resolved"):
            continue
        rd = e.get("resolution_date")
        if rd and str(rd) <= str(as_of):
            out.append(e)
    return out


def recalibration_param(d: Optional[str] = None,
                        entries: Optional[List[Dict[str, Any]]] = None,
                        *, include_evaluation: bool = False) -> Dict[str, Any]:
    """R2-CAL-5: fit the 1-param logit-scale recalibrator over RESOLVED ledger entries.

    Returns ``{slope, n, fitted, enabled}``. ``enabled`` mirrors the
    ``REPORT_RECALIBRATE_FROM_LEDGER`` flag (default OFF) so a caller can fit the
    parameter for inspection yet only APPLY it once explicitly enabled AND enough
    labels exist (``fitted``). Identity slope (1.0) when data is thin → applying it is
    a no-op (degrade-safe; deferred until labels accrue).
    """
    led = entries if entries is not None else read_ledger(d)
    # Foglamp WP1 (1E, I-21)：重校准拟合默认只吃生产行（见 is_production_calibration_row）；
    # include_evaluation=True 仅供评估通道在隔离账本上使用。
    resolved = [
        {"forecast": {"scenarios": e.get("scenarios")}, "outcome": e.get("outcome")}
        for e in led
        if e.get("resolved") and e.get("outcome") and e.get("scenarios")
        and (include_evaluation or is_production_calibration_row(e))
    ]
    enabled = False
    try:
        from ..config import Config
        enabled = bool(getattr(Config, "REPORT_RECALIBRATE_FROM_LEDGER", False))
    except Exception:  # noqa: BLE001
        enabled = False
    if not resolved:
        return {"slope": 1.0, "n": 0, "fitted": False, "enabled": enabled}
    try:
        from .backtest import fit_recalibrator
        fit = fit_recalibrator(resolved)
        fit["enabled"] = enabled
        return fit
    except Exception:  # noqa: BLE001
        return {"slope": 1.0, "n": len(resolved), "fitted": False, "enabled": enabled}


# ---------------------------------------------------------------------------
# MON-1: 市场判定账本（resolutions.jsonl）——锚定市场一旦 resolve，模型概率就有了真值标签
# ---------------------------------------------------------------------------
# 与 scenario 预测的 ledger.jsonl 正交、同目录：这里记「二元预测 × 锚定市场」的判定结果，
# 每条形如 {report_id, forecast_id, market_id, resolved_outcome, model_p,
# market_p_at_research, brier_contribution, resolved_at, ...}。resolution_monitor.py 追加、
# 幂等（(report_id, forecast_id, market_id) 唯一），并据此算持续 Brier。


def _resolutions_file(d: Optional[str] = None) -> str:
    return os.path.join(d or ledger_dir(), "resolutions.jsonl")


def read_market_resolutions(d: Optional[str] = None) -> List[Dict[str, Any]]:
    """读取全部市场判定记录（容忍损坏/半写的尾行；文件缺失 → []）。"""
    out: List[Dict[str, Any]] = []
    path = _resolutions_file(d)
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


def _resolution_key(report_id: Any, forecast_id: Any, market_id: Any) -> str:
    """判定记录的幂等键：同一 (报告, 预测, 市场) 只记一次，重跑不重复入账。"""
    return f"{str(report_id or '')}\x1f{str(forecast_id or '')}\x1f{str(market_id or '')}"


# LOOP-017 P1：晋升的「查重 + 追加」必须是同一临界区。旧实现先读键集再无锁追加——
# 两个并发晋升方（监测线程 × API 线程 / 重跑）都会读到「不存在」然后各写一行，重复
# 入账直接污染持续 Brier。进程内用本锁串行化；进程间用 fcntl.flock 对目标文件加排它
# 锁（advisory，best-effort：平台/文件系统不支持时退化为仅进程内互斥，绝不抛异常）。
_RESOLUTIONS_WRITE_LOCK = threading.Lock()


def _flock_exclusive(f: Any) -> None:
    """尽力对已打开的判定账本文件加进程间排它锁；不支持的平台静默跳过（degrade-safe）。"""
    try:
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    except (ImportError, OSError, ValueError):  # noqa: BLE001 — advisory 锁为增强
        pass


def append_market_resolution(*, report_id: str, forecast_id: str, market_id: str,
                             resolved_outcome: Optional[str], model_p: Optional[float],
                             market_p_at_research: Optional[float],
                             brier_contribution: Optional[float], resolved_at: str,
                             resolved_yes_price: Optional[float] = None,
                             d: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """追加一条市场判定记录（jsonl）；**幂等且并发安全**——同一 (report_id, forecast_id,
    market_id) 已在账本里则跳过并返回 None，故 resolution_monitor 反复重跑不会重复入账、
    不污染 Brier；重复晋升也绝不改写首行（首次入账的 resolved_at/brier 保持原样）。

    LOOP-017 P1：查重与追加在同一临界区内完成（进程内 threading.Lock + 进程间
    fcntl.flock，见 _RESOLUTIONS_WRITE_LOCK）——并发晋升同一判定恰有一个胜者。
    Best-effort：缺 report_id/forecast_id/market_id → None；落盘失败 → None（degrade-safe）。
    返回新写入的 entry；重复/失败 → None。
    """
    rid = str(report_id or "").strip()
    fid = str(forecast_id or "").strip()
    mid = str(market_id or "").strip()
    if not rid or not fid or not mid:
        return None
    key = _resolution_key(rid, fid, mid)
    entry: Dict[str, Any] = {
        "report_id": rid,
        "forecast_id": fid,
        "market_id": mid,
        "resolved_outcome": resolved_outcome,
        "resolved_yes_price": resolved_yes_price,
        "model_p": model_p,
        "market_p_at_research": market_p_at_research,
        "brier_contribution": brier_contribution,
        "resolved_at": resolved_at,
        "schema_version": 1,
    }
    try:
        target = _resolutions_file(d)
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with _RESOLUTIONS_WRITE_LOCK:
            # 以追加模式持有文件句柄再加 flock：锁的生命周期覆盖「读键集 → 判重 →
            # 单次整行写入」，其他遵循同一协议的写者（含跨进程）被排它。
            with open(target, "a", encoding="utf-8") as f:
                _flock_exclusive(f)
                existing = read_market_resolutions(d)
                seen = {_resolution_key(e.get("report_id"), e.get("forecast_id"),
                                        e.get("market_id"))
                        for e in existing}
                if key in seen:
                    return None  # 幂等门：重复晋升 = no-op（with 退出自动释放锁）
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                f.flush()
        return entry
    except OSError:
        return None


def market_brier_summary(d: Optional[str] = None,
                         entries: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """MON-1：对已入账的市场判定记录汇总持续 Brier（模型概率 vs 已判定真值）。

    每条记录的 ``brier_contribution`` = (model_p − y)²，y∈{0,1} 取自市场终态。返回
    ``{n_resolved, mean_brier}``（无记录时 mean_brier=None）。纯读取、无 LLM/无网络。
    """
    recs = entries if entries is not None else read_market_resolutions(d)
    briers = [e.get("brier_contribution") for e in recs
              if isinstance(e.get("brier_contribution"), (int, float))]
    if not briers:
        return {"n_resolved": len(recs), "mean_brier": None}
    return {"n_resolved": len(recs),
            "mean_brier": round(sum(briers) / len(briers), 4)}


def read_data_resolutions(d: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read official-observation outcomes separately from market outcomes."""
    target = os.path.join(d or ledger_dir(), "data_resolutions.jsonl")
    rows: List[Dict[str, Any]] = []
    try:
        with open(target, encoding="utf-8") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        rows.append(row)
                except (ValueError, TypeError):
                    continue
    except OSError:
        pass
    return rows


def append_data_resolution(record: Dict[str, Any], *, d: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Append one verified official outcome, idempotently under the ledger lock.

    Report/forecast/series identity is immutable. A later provider revision is
    evidence for an explicit review, never an automatic rewrite of an outcome.
    """
    import math
    rid = str(record.get("report_id") or "").strip()
    fid = str(record.get("forecast_id") or "").strip()
    series = str(record.get("series") or "").strip()
    observation = record.get("observation")
    probability = record.get("model_p")
    outcome = record.get("resolved_outcome")
    if (not rid or not fid or not series or type(outcome) is not bool
            or not isinstance(observation, dict)
            or isinstance(probability, bool) or not isinstance(probability, (int, float))
            or not math.isfinite(probability) or not 0 <= probability <= 1):
        return None
    entry = dict(record)
    entry.update(report_id=rid, forecast_id=fid, series=series,
                 schema_version=1, resolution_kind="official_data",
                 brier_contribution=round((float(probability) - float(outcome)) ** 2, 4))
    try:
        encoded = json.dumps(entry, ensure_ascii=False, allow_nan=False)
        target = os.path.join(d or ledger_dir(), "data_resolutions.jsonl")
        key = _resolution_key(rid, fid, "data:" + series)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with _RESOLUTIONS_WRITE_LOCK:
            with open(target, "a", encoding="utf-8") as stream:
                _flock_exclusive(stream)
                existing = {
                    _resolution_key(str(row.get("report_id") or "").strip(),
                                    str(row.get("forecast_id") or "").strip(),
                                    "data:" + str(row.get("series") or "").strip())
                    for row in read_data_resolutions(d)
                }
                if key in existing:
                    return None
                stream.write(encoded + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        return entry
    except (OSError, ValueError, TypeError):
        return None


def data_brier_summary(d: Optional[str] = None) -> Dict[str, Any]:
    """Official-data calibration never enters the market-only denominator."""
    import math
    rows = read_data_resolutions(d)
    values = [row.get("brier_contribution") for row in rows]
    values = [float(value) for value in values if isinstance(value, (int, float))
              and not isinstance(value, bool) and math.isfinite(value)]
    return {"n_resolved": len(rows), "mean_brier": round(sum(values) / len(values), 4) if values else None}
