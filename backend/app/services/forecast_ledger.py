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

EVAL-1 (publication-sealed commits): ``ledger.jsonl`` is append-only and never
rewritten or pruned.  Besides the schema_version 1 rows of ``append_forecast``
(``FORECAST_LEDGER_COMMIT_MODE=legacy``), it holds schema_version 2 rows:

- ``row_type='commit'`` (``commit_published_forecast``): the exact audit-sealed
  forecast of a publishable report, idempotent on ``commit_id`` and
  pre-registered on ``target_key`` (question × as_of × record class, plus a
  scenario / seed / provider variant for non-production classes).  The first
  commit for a target is the scored ``primary``; later ones are never-scored
  ``revision`` rows.  Rows are self-contained (question, binaries, provenance,
  publication fingerprint) so they stay settleable after the report folder goes.
- ``row_type='unpublished_terminal'`` (``record_unpublished_terminal``): a
  terminal report that never became publishable, with its reasons, so the
  calibration denominator stays auditable.  Never scored.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import statistics
import threading
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..utils.canonical_json import canonical_json_sha256


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

    EVAL-1 generalises the record-type rule: any ``record_class`` other than
    ``production`` (ensemble members, model comparisons, what-if scenarios,
    evaluation), any ``row_type`` other than ``commit`` (unpublished terminals)
    and every ``calibration_role='revision'`` row are excluded.  Legacy rows that
    carry none of these keys still count.
    """
    if not isinstance(e, dict):
        return False
    if e.get("golden") or e.get("characterization_only"):
        return False
    record_class = str(e.get("record_class") or "").strip().lower()
    if record_class and record_class != "production":
        return False
    return _is_scorable_row(e)


def is_production_primary_commit(e: Any) -> bool:
    """EVAL-3: a production primary commit row, the only forecast target a settlement
    event may label for production calibration (I-21)."""
    return (isinstance(e, dict) and e.get("row_type") == "commit"
            and e.get("calibration_role") == "primary"
            and is_production_calibration_row(e))


def _is_scorable_row(e: Dict[str, Any]) -> bool:
    """EVAL-1: False for rows NO lane may score, whatever its record-class policy.

    An ``unpublished_terminal`` (any ``row_type`` other than ``commit``) has no
    forecast to score, and a ``calibration_role='revision'`` row re-publishes a
    target whose primary is the only scored row. The evaluation lane
    (``include_evaluation=True``) relaxes the record-class rule, never this one.
    """
    if not isinstance(e, dict):
        return False
    if "row_type" in e and str(e.get("row_type") or "").strip().lower() != "commit":
        return False
    return str(e.get("calibration_role") or "").strip().lower() != "revision"


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


def _settlement_fold_default(include_evaluation: bool) -> bool:
    """EVAL-3: FORECAST_LEDGER_SETTLEMENT_FOLD for the production lane. The evaluation lane
    never folds unless asked: its golden rows carry known outcomes, not settlement events,
    so the gate would drop every one of them."""
    if include_evaluation:
        return False
    try:
        from ..config import Config
        return bool(getattr(Config, "FORECAST_LEDGER_SETTLEMENT_FOLD", False))
    except Exception:  # noqa: BLE001 — unreadable config → the historical, unfolded read
        return False


def _calibration_selection(d: Optional[str], entries: Optional[List[Dict[str, Any]]], *,
                           include_evaluation: bool, as_of: Any,
                           fold_settlements: Optional[bool],
                           events: Optional[List[Dict[str, Any]]]
                           ) -> Tuple[List[Dict[str, Any]], int, Dict[str, int]]:
    """EVAL-3: the resolved scenario forecasts calibration may score, shared by
    calibration_summary and recalibration_param → ``(resolved, n_unscoreable, excluded)``.

    ``fold_settlements`` None follows ``_settlement_fold_default``. Folding replaces the
    ledger by ``forecast_resolution.resolved_view`` over the settlement ``events`` (read
    from ``d`` only when neither ``entries`` nor ``events`` is given, so explicit entries
    keep a call hermetic): only production primary commit rows remain, labelled by events
    alone. A candidate is a resolved row with scenarios that passes the record-class rule
    (silently, as before). Under the fold, a candidate outside the view (a legacy row, a
    commit row without the primary role) is counted as ``not_production_primary`` without
    reading any of its own settlement fields, so a hand-edited row never scores. With the
    fold on or an ``as_of`` given, a candidate must pass ``forecast_resolution.admissible``
    — the only point-in-time gate; it must always pass ``is_scoreable_resolution``.
    ``excluded`` counts every candidate rejected, by reason; ``n_unscoreable`` those the
    scoreability check rejected.
    """
    from . import forecast_resolution as fr  # lazy: forecast_resolution imports this module

    def candidate(e: Any) -> bool:
        return (isinstance(e, dict) and bool(e.get("resolved")) and bool(e.get("scenarios"))
                and (_is_scorable_row(e) if include_evaluation
                     else is_production_calibration_row(e)))

    if fold_settlements is None:
        fold = _settlement_fold_default(include_evaluation)
    else:
        fold = bool(fold_settlements)
    led = entries if entries is not None else read_ledger(d)
    excluded: Counter = Counter()
    if fold:
        if events is None:
            events = [] if entries is not None else read_market_resolutions(d)
        n_outside = sum(1 for e in led if not is_production_primary_commit(e) and candidate(e))
        if n_outside:
            excluded[fr.NOT_PRODUCTION_PRIMARY] = n_outside
        led = fr.resolved_view(led, events)
    gated = fold or as_of is not None
    resolved: List[Dict[str, Any]] = []
    n_unscoreable = 0
    for e in led:
        if not candidate(e):
            continue
        if gated:
            ok, reason = fr.admissible(e, as_of)
            if not ok:
                excluded[reason] += 1
                continue
        reason = fr.unscoreable_reason(e)
        if reason is not None:
            excluded[reason] += 1
            n_unscoreable += 1
            continue
        resolved.append({"forecast": {"scenarios": e.get("scenarios")}, "outcome": e.get("outcome")})
    return resolved, n_unscoreable, dict(sorted(excluded.items()))


def calibration_summary(d: Optional[str] = None, entries: Optional[List[Dict[str, Any]]] = None,
                        *, include_evaluation: bool = False, as_of: Any = None,
                        fold_settlements: Optional[bool] = None,
                        events: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Historical calibration over RESOLVED ledger entries (Brier / ECE / count).

    Each resolved entry carries ``outcome`` = the scenario name that actually occurred.
    Returns ``{n_resolved, mean_brier, calibration_error, n_excluded_unscoreable,
    excluded}`` (Nones when nothing resolved); ``mean_brier`` is the multi-class sum
    over scenarios (0-2).

    Foglamp WP1 (1E, I-21): by default only PRODUCTION rows count —
    golden/characterization/evaluation rows are excluded by record type. The
    evaluation lane (``golden_eval``) may opt in with ``include_evaluation=True``
    to score an isolated evaluation ledger; production callers never pass it.
    Revisions and unpublished terminals are never scored in either lane (EVAL-1).

    EVAL-3 (see ``_calibration_selection``): a row whose outcome matches no scenario
    name, or several, is never scored as an all-miss; it is counted in
    ``n_excluded_unscoreable`` and ``excluded`` instead. ``fold_settlements`` (None =
    FORECAST_LEDGER_SETTLEMENT_FOLD on the production lane) folds the settlement
    ``events`` into the production primary commit rows; with the fold on or an
    ``as_of`` date given, only items ``forecast_resolution.admissible`` admits count,
    i.e. known strictly before 00:00Z of ``as_of`` (before now without it). With the
    fold off and no ``as_of``, the selection is the historical one minus unscoreable rows.
    """
    resolved, n_unscoreable, excluded = _calibration_selection(
        d, entries, include_evaluation=include_evaluation, as_of=as_of,
        fold_settlements=fold_settlements, events=events)
    counts = {"n_excluded_unscoreable": n_unscoreable, "excluded": excluded}
    if not resolved:
        return {"n_resolved": 0, "mean_brier": None, "calibration_error": None, **counts}
    try:
        from .backtest import calibration_report
        rep = calibration_report(resolved)
        return {"n_resolved": len(resolved),
                "mean_brier": rep.get("mean_brier"),
                "calibration_error": rep.get("calibration_error"), **counts}
    except Exception:  # noqa: BLE001
        return {"n_resolved": len(resolved), "mean_brier": None, "calibration_error": None,
                **counts}


SHAPE_SUMMARY_VERSION = "prob-shape-summary/v1"
# REPORT-11: (label, path inside objective_signals.probability_shape) of each stat
# shape_summary aggregates per policy group.
_SHAPE_SUMMARY_METRICS = (
    ("scenarios.normalized_entropy", ("scenarios", "normalized_entropy")),
    ("scenarios.max_probability", ("scenarios", "max_probability")),
    ("scenarios.critique_delta.normalized_entropy",
     ("scenarios", "critique_delta", "normalized_entropy")),
    ("binaries.midband_share", ("binaries", "midband_share")),
    ("binaries.extreme_share", ("binaries", "extreme_share")),
)
# Group order in the summary: guard off, guard on, policy unknown.
_SHAPE_GROUP_ORDER = {False: 0, True: 1, None: 2}


def _dig(obj: Any, path: Tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _finite_number(value: Any) -> Optional[float]:
    """``value`` as a finite float, else None (bool, non-numbers, NaN/inf and ints too
    large for a float: a hand-edited or corrupt row must not abort the summary)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _distribution(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "median": None}
    # "+ 0.0" turns -0.0 (e.g. a small negative mean of critique deltas rounded to
    # zero) into 0.0, so the summary never prints "-0.0".
    return {"n": len(values), "mean": round(statistics.fmean(values), 4) + 0.0,
            "median": round(statistics.median(values), 4) + 0.0}


def shape_summary(d: Optional[str] = None, entries: Optional[List[Dict[str, Any]]] = None,
                  *, include_evaluation: bool = False) -> Dict[str, Any]:
    """REPORT-11: per-policy distribution of the probability-shape telemetry.

    Reads each row's ``objective_signals.probability_shape`` (written by
    ``commit_published_forecast`` from the sealed forecast's
    ``quality.probability_shape``) and groups rows by its
    ``policy.binary_symmetric_guard``: False, True, or None when the row carries no
    shape or its policy does not name the flag. Each group reports ``n`` (rows),
    ``n_with_shape`` and, per stat, ``{n, mean, median}`` over the rows carrying it
    (``scenarios.critique_delta.*`` exists only when a critique ran).

    Rows are selected like calibration: by default production rows only
    (``is_production_calibration_row`` — golden, characterization, evaluation and
    other non-production classes, revisions and unpublished terminals excluded);
    ``include_evaluation=True`` relaxes only the record-class rule. ``entries``
    replaces reading the ledger in ``d``. Rows without ``objective_signals`` are
    tolerated: rows committed before REPORT-11 or with FORECAST_PROBABILITY_SHAPE
    off, and every row of FORECAST_LEDGER_COMMIT_MODE=legacy (``append_forecast``
    appends the pre-audit draft and never carries signals), count in the None
    group's ``n`` only. Observability: no gate or calibration reads this.
    """
    led = entries if entries is not None else read_ledger(d)
    groups: Dict[Optional[bool], Dict[str, Any]] = {}
    n_rows = n_with_shape = 0
    for e in led:
        if not (_is_scorable_row(e) if include_evaluation else is_production_calibration_row(e)):
            continue
        n_rows += 1
        shape = _dig(e, ("objective_signals", "probability_shape"))
        shape = shape if isinstance(shape, dict) else None
        flag = _dig(shape, ("policy", "binary_symmetric_guard"))
        group = groups.setdefault(flag if isinstance(flag, bool) else None, {
            "n": 0, "n_with_shape": 0,
            "values": {label: [] for label, _path in _SHAPE_SUMMARY_METRICS}})
        group["n"] += 1
        if shape is None:
            continue
        n_with_shape += 1
        group["n_with_shape"] += 1
        for label, path in _SHAPE_SUMMARY_METRICS:
            value = _finite_number(_dig(shape, path))
            if value is not None:
                group["values"][label].append(value)
    return {
        "version": SHAPE_SUMMARY_VERSION,
        "include_evaluation": bool(include_evaluation),
        "n_rows": n_rows,
        "n_with_shape": n_with_shape,
        "groups": [
            {"binary_symmetric_guard": flag, "n": group["n"],
             "n_with_shape": group["n_with_shape"],
             "metrics": {label: _distribution(values)
                         for label, values in group["values"].items()}}
            for flag, group in sorted(groups.items(), key=lambda kv: _SHAPE_GROUP_ORDER[kv[0]])
        ],
    }


def due_for_resolution(as_of: str, d: Optional[str] = None) -> List[Dict[str, Any]]:
    """Unresolved entries whose resolution_date has passed (≤ as_of). For the scheduler."""
    led = read_ledger(d)
    out = []
    for e in led:
        if e.get("resolved"):
            continue
        # EVAL-1: unpublished terminals and never-scored revisions need no resolution.
        if not _is_scorable_row(e):
            continue
        rd = e.get("resolution_date")
        if rd and str(rd) <= str(as_of):
            out.append(e)
    return out


def recalibration_param(d: Optional[str] = None,
                        entries: Optional[List[Dict[str, Any]]] = None,
                        *, include_evaluation: bool = False, as_of: Any = None,
                        fold_settlements: Optional[bool] = None,
                        events: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """R2-CAL-5: fit the 1-param logit-scale recalibrator over RESOLVED ledger entries.

    Returns ``{slope, n, fitted, enabled, n_excluded_unscoreable, excluded}``.
    ``enabled`` mirrors the shadow-only ``REPORT_RECALIBRATE_FROM_LEDGER`` flag (default
    OFF): nothing applies the slope until a WP14 PromotionDecision. Identity slope (1.0)
    when data is thin → applying it would be a no-op (degrade-safe).

    EVAL-3: selects rows exactly like ``calibration_summary`` (same kwargs, same
    ``admissible`` gate and scoreability filter, same exclusion counts).
    """
    # Foglamp WP1 (1E, I-21)：重校准拟合默认只吃生产行（见 is_production_calibration_row）；
    # include_evaluation=True 仅供评估通道在隔离账本上使用（EVAL-1：修订行/未发布行两道都不计）。
    resolved, n_unscoreable, excluded = _calibration_selection(
        d, entries, include_evaluation=include_evaluation, as_of=as_of,
        fold_settlements=fold_settlements, events=events)
    counts = {"n_excluded_unscoreable": n_unscoreable, "excluded": excluded}
    enabled = False
    try:
        from ..config import Config
        enabled = bool(getattr(Config, "REPORT_RECALIBRATE_FROM_LEDGER", False))
    except Exception:  # noqa: BLE001
        enabled = False
    if not resolved:
        return {"slope": 1.0, "n": 0, "fitted": False, "enabled": enabled, **counts}
    try:
        from .backtest import fit_recalibrator
        fit = fit_recalibrator(resolved)
        fit["enabled"] = enabled
        fit.update(counts)
        return fit
    except Exception:  # noqa: BLE001
        return {"slope": 1.0, "n": len(resolved), "fitted": False, "enabled": enabled, **counts}


# ---------------------------------------------------------------------------
# MON-1: 市场判定账本（resolutions.jsonl）——锚定市场一旦 resolve，模型概率就有了真值标签
# ---------------------------------------------------------------------------
# 与 scenario 预测的 ledger.jsonl 正交、同目录：这里记「二元预测 × 锚定市场」的判定结果，
# 每条形如 {report_id, forecast_id, market_id, resolved_outcome, model_p,
# market_p_at_research, brier_contribution, resolved_at, ...}。resolution_monitor.py 追加、
# 幂等（(report_id, forecast_id, market_id) 唯一），并据此算持续 Brier。


# EVAL-2: resolutions.jsonl rows that carry settlement-event facts (see append_market_resolution).
MARKET_RESOLUTION_EVENT_SCHEMA_VERSION = 2


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
                             d: Optional[str] = None,
                             extra: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """追加一条市场判定记录（jsonl）；**幂等且并发安全**——同一 (report_id, forecast_id,
    market_id) 已在账本里则跳过并返回 None，故 resolution_monitor 反复重跑不会重复入账、
    不污染 Brier；重复晋升也绝不改写首行（首次入账的 resolved_at/brier 保持原样）。

    LOOP-017 P1：查重与追加在同一临界区内完成（进程内 threading.Lock + 进程间
    fcntl.flock，见 _RESOLUTIONS_WRITE_LOCK）——并发晋升同一判定恰有一个胜者。
    Best-effort：缺 report_id/forecast_id/market_id → None；落盘失败 → None（degrade-safe）。
    返回新写入的 entry；重复/失败 → None。

    EVAL-2：非空 ``extra``（settlement event v2 的附加事实：outcome_known_at、
    known_at_basis、prospective、scoring_eligible …）并入记录，``schema_version`` 置 2；
    extra 不能改写上面的基础字段，幂等键与锁不变。extra 为空 → 记录与历史逐字节一致。
    含非 JSON 值（NaN/不可序列化）的 extra → None，不写盘。
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
    if isinstance(extra, dict) and extra:
        for k, v in extra.items():
            if k not in entry:
                entry[k] = v
        entry["schema_version"] = MARKET_RESOLUTION_EVENT_SCHEMA_VERSION
        try:
            json.dumps(entry, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            return None
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


# EVAL-4: the named parameters of append_market_resolution; every other field of a complete
# settlement event travels in its ``extra``.
_RESOLUTION_BASE_KEYS = ("report_id", "forecast_id", "market_id", "resolved_outcome",
                         "resolved_yes_price", "model_p", "market_p_at_research",
                         "brier_contribution", "resolved_at")


def append_settlement_event(event: Any, *, d: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """EVAL-4: append one complete settlement event (``forecast_resolution.build_manual_event``)
    through ``append_market_resolution``: same idempotency key, lock and first-write-wins.
    Returns the written row; None for a non-dict event, a key already recorded or a failed
    write."""
    if not isinstance(event, dict):
        return None
    extra = {k: v for k, v in event.items() if k not in _RESOLUTION_BASE_KEYS}
    return append_market_resolution(
        report_id=event.get("report_id"), forecast_id=event.get("forecast_id"),
        market_id=event.get("market_id"), resolved_outcome=event.get("resolved_outcome"),
        model_p=event.get("model_p"), market_p_at_research=event.get("market_p_at_research"),
        brier_contribution=event.get("brier_contribution"), resolved_at=event.get("resolved_at"),
        resolved_yes_price=event.get("resolved_yes_price"), d=d, extra=extra)


def _is_market_brier_row(e: Any) -> bool:
    """EVAL-2: a market-settled row (legacy rows carry no source_kind). Grace terminals
    (source_kind 'terminal'), other label sources and 50/50 ambiguous settlements are
    not market resolutions of a YES/NO outcome, so they never enter the market Brier."""
    return (isinstance(e, dict) and e.get("source_kind") in (None, "polymarket")
            and e.get("resolution_status") != "ambiguous")


def market_brier_summary(d: Optional[str] = None,
                         entries: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """MON-1：对已入账的市场判定记录汇总持续 Brier（模型概率 vs 已判定真值）。

    每条记录的 ``brier_contribution`` = (model_p − y)²，y∈{0,1} 取自市场终态。返回
    ``{n_resolved, mean_brier}``（无记录时 mean_brier=None）。纯读取、无 LLM/无网络。
    EVAL-2：只计市场判定行（见 _is_market_brier_row）；旧行不受影响。
    """
    recs = [e for e in (entries if entries is not None else read_market_resolutions(d))
            if _is_market_brier_row(e)]
    briers = [e.get("brier_contribution") for e in recs
              if isinstance(e.get("brier_contribution"), (int, float))]
    if not briers:
        return {"n_resolved": len(recs), "mean_brier": None}
    return {"n_resolved": len(recs),
            "mean_brier": round(sum(briers) / len(briers), 4)}


def _unit_probability(value: Any) -> Optional[float]:
    """A finite probability in [0, 1], else None (bools are not probabilities)."""
    if isinstance(value, bool):
        return None
    try:
        p = float(value)
    except (TypeError, ValueError):
        return None
    return p if math.isfinite(p) and 0.0 <= p <= 1.0 else None


def binary_calibration_summary(d: Optional[str] = None, *, as_of: Any = None,
                               events: Optional[List[Dict[str, Any]]] = None,
                               entries: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """EVAL-3: binary-scale calibration over the folded binary settlement events.

    Folds ``events`` (default: ``resolutions.jsonl`` in ``d``) per item with
    ``forecast_resolution.fold_binary_items``, legacy rows proven against ``entries``
    (default: ``ledger.jsonl`` in ``d``), and keeps the items ``admissible(item, as_of)``
    admits. Each is scored as the YES/NO two-scenario forecast ``append_golden_result``
    writes (YES = model_p, NO = 1 - model_p) through ``backtest.calibration_report``;
    that multi-class sum is twice the binary Brier for a YES/NO pair, so ``mean_brier``
    is halved onto the binary 0-1 scale. Returns ``{n_resolved, mean_brier,
    calibration_error, excluded, as_of, scale: 'binary'}``; ``excluded`` counts by
    reason every folded item that is not scored (admissibility reasons, ``not_settled``
    for a status other than 'settled', ``no_binary_outcome``,
    ``invalid_model_probability``).
    """
    from . import forecast_resolution as fr  # lazy: forecast_resolution imports this module

    items = fr.fold_binary_items(
        events if events is not None else read_market_resolutions(d),
        targets=entries if entries is not None else read_ledger(d))
    resolved: List[Dict[str, Any]] = []
    excluded: Counter = Counter()
    for key in sorted(items):
        item = items[key]
        ok, reason = fr.admissible(item, as_of)
        if not ok:
            excluded[reason] += 1
            continue
        if item.get("resolution_status") != "settled":
            excluded["not_settled"] += 1
            continue
        outcome = str(item.get("outcome") or "").strip().upper()
        if outcome not in ("YES", "NO"):
            excluded["no_binary_outcome"] += 1
            continue
        p = _unit_probability(item.get("model_p"))
        if p is None:
            excluded["invalid_model_probability"] += 1
            continue
        resolved.append({"forecast": {"scenarios": [
            {"name": "YES", "probability": round(p, 4)},
            {"name": "NO", "probability": round(1.0 - p, 4)},
        ]}, "outcome": outcome})
    out: Dict[str, Any] = {"n_resolved": len(resolved), "mean_brier": None,
                           "calibration_error": None, "excluded": dict(sorted(excluded.items())),
                           "as_of": as_of, "scale": "binary"}
    if resolved:
        try:
            from .backtest import calibration_report
            rep = calibration_report(resolved)
            multi_class = rep.get("mean_brier")
            if isinstance(multi_class, (int, float)):
                out["mean_brier"] = round(multi_class / 2.0, 4)
            out["calibration_error"] = rep.get("calibration_error")
        except Exception:  # noqa: BLE001 — scoring failure leaves the numbers None
            pass
    return out


# ---------------------------------------------------------------------------
# EVAL-1: publication-sealed commits (schema_version 2 rows in ledger.jsonl)
# ---------------------------------------------------------------------------
# A scored row must describe exactly what was published: the caller
# (services/ledger_commit.py) only commits the audit-sealed forecast.json of a
# report whose publication_status is publishable. Identity is two-level:
#   commit_id  = sha256(report_id:forecast_sha256)  → re-committing the same
#                publication is a no-op, even after resolution;
#   target_key = cjson({v, q, as_of, record_class}) → pre-registration: the first
#                commit for a question at an as-of date is the scored primary, any
#                later publication is a never-scored revision (run/seed are
#                provenance, not identity, so a regenerated report cannot replace
#                a primary whose outcome may already be known). Non-production
#                classes add a ``variant`` (what-if scenario, ensemble seed,
#                compared provider) so distinct scenarios / members / providers of
#                one question are separate targets, not revisions of each other;
#                production keys never carry one.

LEDGER_COMMIT_SCHEMA_VERSION = 2
# Provenance copied into commit rows when present; anything else in the caller's
# context is ignored so rows keep one stable, reviewable shape. EVAL-13: an evaluation
# row routed there fail-closed (no run identity) names why (evaluation_fail_closed) and,
# for a fork of an evaluation run, which run (evaluation_marker_pipeline_id).
_PROVENANCE_KEYS = ("pipeline_id", "simulation_id", "run_ref", "seed", "run_kind",
                    "config_hash", "eval_run_id", "cell_id", "evaluation_fail_closed",
                    "evaluation_marker_pipeline_id")
UNPUBLISHED_MAX_REASONS = 10
UNPUBLISHED_REASON_MAX_CHARS = 300
_BINARY_ANCHOR_MAX_CHARS = 300
# EVAL-13: target_question_id / target_bind tie an evaluation row's binary to its golden
# question without reopening forecast.json; only an evaluation run's extraction sets them.
_COMPACT_BINARY_OPTIONAL_KEYS = ("market_anchor", "market_influence",
                                 "scenario_membership", "target",
                                 "target_question_id", "target_bind")

# Same protocol as _RESOLUTIONS_WRITE_LOCK: the duplicate/revision decision and
# the single append happen in one critical section (in-process lock + advisory
# fcntl.flock on the open append handle), so concurrent reports (the seed
# ensemble runs several at once) can never both become the primary.
_LEDGER_WRITE_LOCK = threading.Lock()

# 判定标准里显式写出的 ISO 日期（如「by 2026-11-03」）优先于 horizon_year 年底代理。
# （EVAL-1：连同 binary_resolution_date 从 scripts/resolution_monitor.py 原样迁入，
# 供账本行自描述二元预测的判定日；监测脚本保留同名别名。）
_ISO_DATE_RE = re.compile(r"(?<!\d)(20\d{2}-\d{2}-\d{2})(?!\d)")

# A range endpoint is a year 1900-2099 or a full ISO date; '->' precedes '-' so an
# ASCII arrow is one join, not a dash followed by '>'.
_RANGE_POINT = r"(?:19|20)\d{2}(?:-\d{2}-\d{2})?"
_RANGE_JOIN = r"\s*(?:->|→|-|–|—|~|～|to|至)\s*"
_RANGE_RE = re.compile(
    rf"(?<!\d)({_RANGE_POINT})年?{_RANGE_JOIN}({_RANGE_POINT})(?!\d)", re.IGNORECASE)
# A fiscal-style range with a two-digit end year ('FY2026-27', '2026/27'). The end is
# read in the start year's century and must be later than the start, so a year-month
# ('2026-07') never qualifies, and a full date ('2010-11-05') is excluded outright.
_SHORT_RANGE_RE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})\s*[-–—/]\s*(\d{2})(?!\d)(?!\s*[-/]\s*\d)")
# An as-of note ('2030 (as-of 2026-07-09)') dates the forecast, not its resolution.
_AS_OF_NOTE_RE = re.compile(r"[(（]\s*as[\s_-]*of\b[^)）]{0,80}[)）]", re.IGNORECASE)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_calendar_date(text: str) -> bool:
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%Y-%m-%d") == text
    except ValueError:
        return False


def _range_point_end(point: str) -> Optional[str]:
    """Last day covered by a range endpoint: a year → its 31 Dec; a real date → itself."""
    if len(point) == 4:
        return f"{point}-12-31"
    return point if _is_calendar_date(point) else None


def resolution_date_for_horizon(horizon: Optional[str]) -> Optional[str]:
    """Range-aware resolution date for a free-text horizon.

    A horizon naming a range resolves at its END, not its start. Endpoints are
    years 1900-2099 or full ISO dates joined by '-', an en/em dash, '~', '→',
    '->', 'to' or '至'; a year endpoint covers its whole year ('2026-2036' →
    '2036-12-31', '2026-01-01 to 2035' → '2035-12-31', '2026-07-08 → 2031-12-31'
    → '2031-12-31'). A two-digit end year reads in the start's century
    ('FY2026-27' → '2027-12-31'). When the text names a range, the result is the
    LATEST of every valid range end and ``_year_end``'s reading, so a baseline
    range ('from 2019-2020 levels by 2030') can never pull the date earlier: a
    late resolution date only delays settlement, an early one settles
    prematurely. For the same reason a parenthesised as-of note ('2030 (as-of
    2026-07-09)') is ignored unless nothing else in the text resolves. Any
    other text without a valid range delegates to ``_year_end`` unchanged.
    """
    if not horizon:
        return None
    original = str(horizon)
    text = _AS_OF_NOTE_RE.sub(" ", original)
    range_ends: List[str] = []
    for m in _RANGE_RE.finditer(text):
        ends = [_range_point_end(point) for point in m.groups()]
        if all(ends):
            range_ends.append(max(ends))
    for m in _SHORT_RANGE_RE.finditer(text):
        start, end_2d = int(m.group(1)), int(m.group(2))
        if end_2d > start % 100:
            range_ends.append(f"{start - start % 100 + end_2d}-12-31")
    year_end = _year_end(text) or (_year_end(original) if text != original else None)
    if not range_ends:
        return year_end
    return max(range_ends + ([year_end] if year_end else []))


def question_sha256(text: Any) -> str:
    """Identity hash of a forecast question: NFKC + casefold + collapsed whitespace.

    Cosmetic differences (full-width characters, case, line wrapping) must not
    split one question into several pre-registration targets.
    """
    normalized = " ".join(
        unicodedata.normalize("NFKC", str(text or "")).casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def binary_resolution_date(binary: Dict[str, Any]) -> Optional[str]:
    """一条二元预测的判定日期（ISO）：优先 resolution_criteria/resolution_source 里显式写出的
    完整 ISO 日期；否则用 horizon_year 的年底（YYYY-12-31）作代理。都无 → None。"""
    if not isinstance(binary, dict):
        return None
    for key in ("resolution_criteria", "resolution_source", "statement"):
        m = _ISO_DATE_RE.search(str(binary.get(key) or ""))
        if m:
            return m.group(1)
    hy = binary.get("horizon_year")
    try:
        y = int(float(hy)) if hy not in (None, "") else None
    except (TypeError, ValueError):
        y = None
    if y and 2000 <= y <= 2100:
        return f"{y}-12-31"
    return None


def compact_binary(binary: Dict[str, Any]) -> Dict[str, Any]:
    """Self-contained copy of one binary forecast for a commit row.

    ``statement`` and ``resolution_criteria`` are copied VERBATIM: the market
    anchor's ``forecast_contract_sha256`` hashes exactly those two strings, so
    any normalisation here would break later settlement verification.
    """
    row: Dict[str, Any] = {
        "id": binary.get("id"),
        "proposition_id": binary.get("proposition_id"),
        "statement": binary.get("statement"),
        "probability": binary.get("probability"),
        "resolution_criteria": binary.get("resolution_criteria"),
        "resolution_source": binary.get("resolution_source"),
        "theme": binary.get("theme"),
        "horizon_year": binary.get("horizon_year"),
        "resolution_date": binary_resolution_date(binary),
        "base_rate_anchor": str(binary.get("base_rate_anchor") or "")[:_BINARY_ANCHOR_MAX_CHARS],
        "source": binary.get("source"),
    }
    for key in _COMPACT_BINARY_OPTIONAL_KEYS:
        if binary.get(key) is not None:
            row[key] = copy.deepcopy(binary[key])
    return row


def run_ref_for(context: Optional[Dict[str, Any]]) -> Optional[str]:
    """The run a ledger row came from: pipeline_id, else ``sim:<simulation_id>``."""
    ctx = context if isinstance(context, dict) else {}
    pipeline_id = str(ctx.get("pipeline_id") or "").strip()
    if pipeline_id:
        return pipeline_id
    simulation_id = str(ctx.get("simulation_id") or "").strip()
    return f"sim:{simulation_id}" if simulation_id else None


def _provenance_fields(provenance: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Whitelisted, present-only provenance for a commit row (run_ref is derived)."""
    src = provenance if isinstance(provenance, dict) else {}
    out: Dict[str, Any] = {}
    for key in _PROVENANCE_KEYS:
        if key == "run_ref":
            value: Any = run_ref_for(src)
        else:
            value = src.get(key)
        if value is None or value == "":
            continue
        if key == "seed":
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
        else:
            value = str(value)
        out[key] = value
    return out


def _route_dir(d: Optional[str], record_class: Any) -> str:
    """Foglamp WP1 record-class redirect (mirrors append_golden_result): evaluation
    rows aimed at the production ledger land in evaluation_ledger_dir()."""
    target = d or ledger_dir()
    if (str(record_class or "").strip().lower() == "evaluation"
            and os.path.abspath(target) == os.path.abspath(ledger_dir())):
        return evaluation_ledger_dir()
    return target


def has_report_row(report_id: str, *, record_class: str = "production",
                   d: Optional[str] = None) -> bool:
    """True when the ledger that ``record_class`` routes to holds any row for
    ``report_id`` (a commit, an unpublished terminal or a legacy schema_version 1 row)."""
    rid = str(report_id or "").strip()
    return bool(rid) and any(isinstance(e, dict) and e.get("report_id") == rid
                             for e in read_ledger(_route_dir(d, record_class)))


def commit_published_forecast(forecast: Optional[Dict[str, Any]], *, report_id: str,
                              question: Optional[str], language: Optional[str],
                              as_of_date: str, as_of_source: str,
                              publication: Dict[str, Any], record_class: str = "production",
                              provenance: Optional[Dict[str, Any]] = None,
                              d: Optional[str] = None,
                              committed_at: Optional[str] = None,
                              target_variant: Optional[Dict[str, Any]] = None,
                              characterization_only: bool = False,
                              objective_signals: Optional[Dict[str, Any]] = None,
                              ) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Append one publication-sealed forecast; returns ``(status, row)``.

    ``status`` is ``committed`` (new scored primary), ``revision`` (another
    publication for an already-committed target; appended, never scored),
    ``duplicate`` (this exact publication is already in the ledger; nothing
    written, the existing row is returned) or ``error`` (invalid input or I/O
    failure; nothing written). ``forecast`` must be the audit-sealed object
    whose bytes hash to ``publication['forecast_sha256']``. ``target_variant``
    (non-production classes only; ignored for production) joins the target key
    and is stored on the row as ``target_variant``. ``characterization_only=True``
    (EVAL-13 evaluation runs) stamps the row so no production reader ever scores
    it; the default leaves the row shape unchanged.

    REPORT-11: a non-empty ``objective_signals`` dict (deterministic telemetry of
    the sealed forecast, e.g. ``{'probability_shape': ...}``) is stored as a copy
    under ``objective_signals``; it never joins the commit id or the target key.
    Signals that are not strict JSON are dropped (the row then carries
    ``objective_signals_dropped: true``) rather than failing the commit. None (the
    default) leaves the row shape unchanged.
    """
    rid = str(report_id or "").strip()
    pub = publication if isinstance(publication, dict) else {}
    forecast_sha = str(pub.get("forecast_sha256") or "").strip()
    # as_of_date is part of the pre-registration key: only a canonical calendar
    # date may enter it (fail closed rather than key a row on a guess).
    if (not rid or not forecast_sha or not isinstance(forecast, dict)
            or not isinstance(as_of_date, str) or not _is_calendar_date(as_of_date)):
        return "error", None
    scenarios = [
        {"name": s.get("name"), "probability": s.get("probability"),
         "resolution_criteria": s.get("resolution_criteria")}
        for s in (forecast.get("scenarios") or []) if isinstance(s, dict)
    ]
    if not scenarios:
        return "error", None
    rc = str(record_class or "").strip() or "production"
    q_text = str(question or "")
    try:
        from ..config import Config
        max_chars = max(0, int(getattr(Config, "FORECAST_LEDGER_QUESTION_MAX_CHARS", 4000)))
    except (TypeError, ValueError):
        max_chars = 4000
    q_sha = question_sha256(q_text)
    commit_id = hashlib.sha256(f"{rid}:{forecast_sha}".encode("utf-8")).hexdigest()
    key_payload: Dict[str, Any] = {"v": 1, "q": q_sha, "as_of": as_of_date, "record_class": rc}
    variant = (dict(target_variant)
               if isinstance(target_variant, dict) and target_variant and rc != "production"
               else None)
    if variant:
        key_payload["variant"] = variant
    try:
        target_key = canonical_json_sha256(key_payload)
    except (TypeError, ValueError):
        return "error", None
    hz = str(forecast.get("horizon") or "").strip() or None
    row: Dict[str, Any] = {
        "schema_version": LEDGER_COMMIT_SCHEMA_VERSION,
        "row_type": "commit",
        "commit_id": commit_id,
        "target_key": target_key,
        "calibration_role": "primary",
        "revision_of": None,
        "record_class": rc,
        "report_id": rid,
        "horizon": hz,
        "resolution_date": resolution_date_for_horizon(hz),
        "created_at": committed_at or _utc_now_iso(),
        "scenarios": scenarios,
        "confidence": forecast.get("confidence"),
        # Kept so legacy readers (calibration_summary / due_for_resolution) work;
        # never mutated — outcomes belong to separate settlement records.
        "resolved": False,
        "outcome": None,
        "question": q_text[:max_chars],
        # The cap is never silent: question_sha256 hashes the FULL text, so a reader
        # re-hashing a truncated ``question`` can tell why it does not match.
        "question_chars": len(q_text),
        "question_truncated": len(q_text) > max_chars,
        "question_sha256": q_sha,
        "language": language,
        "as_of_date": as_of_date,
        "as_of_source": as_of_source,
        "publication": {
            "authority": pub.get("authority") or "final_audit",
            "policy_version": pub.get("policy_version"),
            "markdown_sha256": pub.get("markdown_sha256"),
            "forecast_sha256": forecast_sha,
        },
        "binary_forecasts": [compact_binary(b) for b in (forecast.get("binary_forecasts") or [])
                             if isinstance(b, dict)],
    }
    if variant:
        row["target_variant"] = variant
    if characterization_only:
        row["characterization_only"] = True
    if isinstance(objective_signals, dict) and objective_signals:
        try:
            json.dumps(objective_signals, ensure_ascii=False, allow_nan=False)
            row["objective_signals"] = copy.deepcopy(objective_signals)
        except (TypeError, ValueError):
            # Telemetry is optional: the scored row still lands, and says what it lost.
            row["objective_signals_dropped"] = True
    row.update(_provenance_fields(provenance))
    try:
        # Reject non-JSON / NaN rows before touching the ledger file at all.
        json.dumps(row, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return "error", None
    try:
        target_dir = _route_dir(d, rc)
        target = _ledger_file(target_dir)
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with _LEDGER_WRITE_LOCK:
            with open(target, "a", encoding="utf-8") as f:
                _flock_exclusive(f)
                first_for_target: Optional[Dict[str, Any]] = None
                primary_for_target: Optional[Dict[str, Any]] = None
                for e in read_ledger(target_dir):
                    if not isinstance(e, dict) or e.get("row_type") != "commit":
                        continue
                    if e.get("commit_id") == commit_id:
                        return "duplicate", e  # 幂等门：同一份封印发布只入账一次
                    if e.get("target_key") == target_key:
                        first_for_target = first_for_target or e
                        if primary_for_target is None and e.get("calibration_role") == "primary":
                            primary_for_target = e
                anchor = primary_for_target or first_for_target
                status = "committed"
                if anchor is not None:
                    row["calibration_role"] = "revision"
                    row["revision_of"] = anchor.get("commit_id")
                    status = "revision"
                f.write(_line_boundary(target)
                        + json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                f.flush()
        return status, row
    except OSError:
        return "error", None


def _line_boundary(path: str) -> str:
    """'\\n' when the ledger file ends mid-line (a torn write), else ''.

    A row appended straight after an unterminated fragment (ENOSPC mid-write, a
    crashed writer) would merge into it, and read_ledger drops the merged line:
    the row would be reported written yet stay invisible to every idempotency
    check. The newline isolates the fragment on its own (skipped) line. Called
    inside the write lock, before the single append.
    """
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            if fh.tell() == 0:
                return ""
            fh.seek(-1, os.SEEK_END)
            return "" if fh.read(1) == b"\n" else "\n"
    except OSError:
        return ""


def record_unpublished_terminal(*, report_id: str, question_sha256: Optional[str],
                                record_class: str, run_ref: Optional[str], reasons: Any,
                                d: Optional[str] = None, recorded_at: Optional[str] = None,
                                ) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Record a terminal report that never became publishable; ``(status, row)``.

    ``status`` is ``recorded``, ``duplicate`` (this report already has an
    unpublished row; nothing written) or ``error``. The row carries no scenarios
    and no resolution date, so no reader can ever score it; it exists so the
    denominator of published forecasts stays auditable. ``reasons`` keeps the
    first UNPUBLISHED_MAX_REASONS, each capped at UNPUBLISHED_REASON_MAX_CHARS;
    ``reasons_total`` / ``reasons_truncated`` say what the caps removed.
    """
    rid = str(report_id or "").strip()
    if not rid:
        return "error", None
    rc = str(record_class or "").strip() or "production"
    if isinstance(reasons, str):
        reasons = [reasons]
    all_reasons = [str(r) for r in list(reasons or [])]
    kept = [r[:UNPUBLISHED_REASON_MAX_CHARS] for r in all_reasons[:UNPUBLISHED_MAX_REASONS]]
    row: Dict[str, Any] = {
        "schema_version": LEDGER_COMMIT_SCHEMA_VERSION,
        "row_type": "unpublished_terminal",
        "report_id": rid,
        "question_sha256": question_sha256,
        "record_class": rc,
        "run_ref": run_ref,
        "reasons": kept,
        "reasons_total": len(all_reasons),
        "reasons_truncated": kept != all_reasons,
        "recorded_at": recorded_at or _utc_now_iso(),
    }
    try:
        json.dumps(row, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return "error", None
    try:
        target_dir = _route_dir(d, rc)
        target = _ledger_file(target_dir)
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with _LEDGER_WRITE_LOCK:
            with open(target, "a", encoding="utf-8") as f:
                _flock_exclusive(f)
                for e in read_ledger(target_dir):
                    if (isinstance(e, dict) and e.get("row_type") == "unpublished_terminal"
                            and e.get("report_id") == rid):
                        return "duplicate", e
                f.write(_line_boundary(target)
                        + json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                f.flush()
        return "recorded", row
    except OSError:
        return "error", None
