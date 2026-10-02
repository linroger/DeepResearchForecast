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

EVAL-3（影子可观测面）：``run`` 与 ``summary`` 的持续校准一律走结算折叠——情景校准
``calibration_summary(fold_settlements=True)``、二元校准 ``binary_calibration_summary``，
两者只计 forecast_resolution.admissible() 放行的条目，其余按原因计入 ``excluded``；
Running score 标注 Brier 口径（情景 multi-class sum, 0-2；二元 binary, 0-1）；未经闸门的
market_brier 行标明 ungated / not calibration，免被误读为校准数。

EVAL-5 (FORECAST_SKILL_SCORING, default on; read-only): the run_monitor result (each ``run``)
and the ``summary`` payload add ``market_skill`` (``backtest.market_skill_report``, schema
market-skill/v1; the ``run`` CLI's per-report rows do not carry it): each folded binary
settlement (``fold_binary_items`` + ``admissible``, never raw event lines) is joined at read
time with the anchor its forecast saw (``enrich_market_rows``) and scored against that market
price, in an exact-equivalence headline stratum, a proxy stratum and an all_produced stratum;
monitor_report.md gains '## Skill vs the market it saw'. resolutions.jsonl is never written
by this path; flag off → the monitor's output is byte-identical to before.

设计与 scripts/scheduled_rerun.py 同构：脚本自撑 sys.path、Config 旋钮经 getattr 读取
（本文件不拥有 config.py）、全链路 degrade-safe——任何网络失败只产出**部分**报告，
绝不抛异常、绝不改动任何在线管线语义。``--dry-run`` 全程不写盘（纯观测）。

命令行
------
    python scripts/resolution_monitor.py run <report_id|pipeline_id> [--dry-run]
    python scripts/resolution_monitor.py run --all-recent [N] [--dry-run]   # 最近 N 份报告（缺省 N=RESOLUTION_MONITOR_RECENT_N）
    python scripts/resolution_monitor.py settle [--dry-run]                 # EVAL-2：扫描账本 primary commit 行并追加结算事件
    python scripts/resolution_monitor.py summary                            # 只打印账本里的持续 Brier / 校准 / market_skill（无网络）
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

# ── 让脚本无论从哪个 cwd 调用都能 import 到 backend 的 app 包（与 scheduled_rerun.py 一致）──
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.config import Config  # noqa: E402
from app.services import backtest as _backtest  # noqa: E402
from app.services import forecast_extractor as _extractor  # noqa: E402
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


def skill_scoring_enabled() -> bool:
    """EVAL-5: add market_skill to ``run`` / ``summary`` and its monitor_report.md section."""
    return bool(getattr(Config, "FORECAST_SKILL_SCORING", True))


def skill_min_n() -> int:
    return max(1, _cfg_int("FORECAST_SKILL_MIN_N", 10))


def divergence_min_confidence() -> float:
    """The confidence floor of the 10pp revision rule (FORECAST_MARKET_DIVERGENCE_MIN_CONFIDENCE).

    Read like enforce_market_divergence reads it for every finite value, and an unparseable
    or NaN one falls back to 0.6 on both sides. They part only on ±inf, which the environment
    cannot set (config_audit.sanitize_numeric_env drops a non-finite value before Config
    reads it), so only a value assigned to Config directly: enforce compares against it as
    is (+inf: no candidate, -inf: every candidate), while here it also falls back to 0.6,
    because market_skill_report takes a finite floor only and the monitor must not raise."""
    floor = _cfg_float("FORECAST_MARKET_DIVERGENCE_MIN_CONFIDENCE", 0.6)
    return floor if math.isfinite(floor) else 0.6


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


# meta.json 的 created_at 由 datetime.now().isoformat() 写出（主机本地时间、无时区）：
# 无时区按本地时间读并换算 UTC；带时区直接换算；其他 → None。与人工结算（EVAL-4
# load_manual_target）共用同一实现，两处永不分叉。
_local_stamp_to_utc = _settlement.local_stamp_to_utc


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


# EVAL-6：锚点的价时溯源键（market_anchor.price_time / price_time_basis），成对透传。
_PRICE_TIME_KEYS = ("price_time", "price_time_basis")


def _carry_price_time(src: Dict[str, Any], dst: Dict[str, Any]) -> None:
    """src 的 price_time 与 price_time_basis 都是非空字符串时，把这一对原样拷进 dst；
    缺任一键（或手改 / 畸形锚点只剩半对）则两键都不写，price_track 里绝不出现半对溯源。"""
    if all(isinstance(src.get(key), str) and src[key].strip() for key in _PRICE_TIME_KEYS):
        for key in _PRICE_TIME_KEYS:
            dst[key] = src[key]


def build_price_rows(anchored: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把锚定预测拍平成 requote_markets 的输入行（每条预测一行，携带回填所需上下文）。

    EVAL-6：锚点带完整的 price_time + price_time_basis 一对（price_at_research 的取价时刻与
    来源）时原样带上，供 price_track 溯源；锚点没有或只剩半对则两键都不出现（旧锚点的行逐字节
    不变）。"""
    rows: List[Dict[str, Any]] = []
    for b in anchored:
        a = b.get("market_anchor") or {}
        mid = str(a.get("market_id") or "").strip()
        if not mid:
            continue
        research = _coerce_float(a.get("price_at_research"))
        if research is None:
            research = _coerce_float(a.get("implied_yes_prob"))
        row = {
            "market_id": mid,
            "question": a.get("question"),
            "implied_yes_prob": _coerce_float(a.get("implied_yes_prob")),
            "price_at_research": research,
            "forecast_id": b.get("id"),
            "statement": b.get("statement"),
        }
        _carry_price_time(a, row)
        rows.append(row)
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
                        as_of: str, *,
                        attested: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
    """指标检查：判定日期已过（≤ as_of）但无市场判定可依的二元预测 → 需人工判定。

    「有市场判定可依」= 该预测锚点市场已 resolved。无锚点、或锚点市场尚未判定，且判定日期
    已过 → 列入清单。纯函数（对**全部**二元预测扫描，不止锚定的那些）。
    EVAL-4：attested = 本报告在账本里已有有效人工证明（forecast_resolution.attested_items）
    的预测 id——已判定，不再催（None = 不过滤）。"""
    out: List[Dict[str, Any]] = []
    for b in binaries or []:
        if not isinstance(b, dict):
            continue
        if attested and str(b.get("id") or "").strip() in attested:
            continue  # 已有人工证明
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


def _num(v: Any) -> str:
    return f"{v:.4f}" if isinstance(v, (int, float)) and not isinstance(v, bool) else "—"


def _interval(ci: Any, fmt: Callable[[Any], str]) -> str:
    return f"{fmt(ci[0])}–{fmt(ci[1])}" if isinstance(ci, list) and len(ci) == 2 else "—"


def _render_market_skill(skill: Dict[str, Any]) -> List[str]:
    """EVAL-5 「## Skill vs the market it saw」段：分层计数、未计分原因、模型 vs 市场 Brier、
    技能、Δ 置信区间、命中率 vs 市场隐含零假设、无边际计数、expired_unresolved；
    insufficient_data 的层标 indicative。"""
    lines = ["", "## Skill vs the market it saw", ""]
    if skill.get("error"):
        lines.append(f"_Market skill unavailable this run: {_cell(skill['error'])}._")
        return lines
    strata = skill.get("strata") or {}
    lines += [
        "| Stratum | Scored (reports) | Model Brier | Market Brier | Skill vs market | "
        "Δ Brier market − model (95% CI) | Edge hit rate (95% CI) vs market null | "
        "Edge / no edge / low conf. / unknown | Price time basis |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name in _backtest.SKILL_STRATA:
        st = strata.get(name) or {}
        div = st.get("divergence") or {}
        edge = div.get("edge") or {}
        basis = st.get("price_time_basis") or {}
        label = f"{name} (indicative)" if st.get("insufficient_data") else name
        lines.append("| " + " | ".join([
            label,
            f"{st.get('n_scored', 0)} ({st.get('n_reports', 0)})",
            _num(st.get("mean_brier_model")),
            _num(st.get("mean_brier_market")),
            _num(st.get("brier_skill_vs_market")),
            f"{_num(st.get('mean_brier_delta'))} ({_interval(st.get('brier_delta_ci95'), _num)})",
            f"{_pct(edge.get('hit_rate'))} ({_interval(edge.get('hit_rate_ci95'), _pct)}) "
            f"vs {_pct(edge.get('null_hit_rate'))}",
            f"{edge.get('n', 0)} / {div.get('n_no_edge_claimed', 0)} / "
            f"{div.get('n_ineligible_low_confidence', 0)} / {div.get('n_eligibility_unknown', 0)}",
            ", ".join(f"{key} {basis.get(key, 0)}"
                      for key in _backtest.PRICE_TIME_BASES + ("none",)),
        ]) + " |")
    headline_div = (strata.get("headline") or {}).get("divergence") or {}
    lines += [
        "",
        f"- Unscored by reason: {_reason_counts(skill.get('unscored'))}",
        "- Expired unresolved (anchored, past resolution date, no settlement yet): "
        f"**{skill.get('expired_unresolved', '—')}**",
        "- Headline edges revised toward the market / retained divergence: "
        f"**{(headline_div.get('revised_toward_market') or {}).get('n', 0)}** / "
        f"**{(headline_div.get('retained_divergence') or {}).get('n', 0)}**",
        f"- Proxy reasons: {_reason_counts((strata.get('proxy') or {}).get('proxy_reasons'))}; "
        "rows of reports not publishable at issue in all_produced: "
        f"**{(strata.get('all_produced') or {}).get('n_withheld', 0)}**",
        "- headline = settled, point-in-time admissible, exact-equivalence anchor with a dated "
        "price; proxy = near/loose equivalence or an undated price, never pooled with it; "
        "all_produced = headline criteria plus reports withheld at issue, never a headline; "
        f"indicative = fewer than {skill.get('min_n', '—')} scored rows. An edge is "
        f"|model − market| > {_pct(skill.get('divergence_deadband'))} at match confidence ≥ "
        f"{skill.get('min_match_confidence', '—')} (the revision rule).",
        "- The market price is the anchor price the forecast saw, dated by its price time basis: "
        "'requote' = a report-time requote, 'observed' = the research bridge's fetch of that "
        "market row, 'snapshot' = a snapshot's as_of (an upper bound on the price's time), "
        "none = undated; so this measures the published market-aware forecast, not "
        "information independent of the market.",
    ]
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
                      settlement_events: Optional[List[Dict[str, Any]]] = None,
                      binary_calibration: Optional[Dict[str, Any]] = None,
                      market_skill: Optional[Dict[str, Any]] = None) -> str:
    """把一次监测结果渲染成确定性 markdown（无 LLM）。空信号也产出可读骨架。

    EVAL-2：传入 ``settlement``（结算计数）时追加「## Settlement」段；缺省 None → 输出不变。
    EVAL-3：Running score 标注 Brier 口径（情景 = multi-class sum, 0-2；二元 = binary, 0-1），
    未经闸门的 market_brier 行标明 ungated / not calibration；
    ``calibration`` 带 ``excluded`` 时列出按原因的排除计数；传入 ``binary_calibration``
    （forecast_ledger.binary_calibration_summary）时追加结算折叠后的二元校准行。
    EVAL-5：传入 ``market_skill``（market_skill_summary）时在 Running score 之后追加
    「## Skill vs the market it saw」段；缺省 None → 输出逐字节不变。"""
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
        f"- Market-resolved binary forecasts (all settlements, ungated; not calibration): "
        f"**{mb_n}**; mean Brier (binary, 0-1): **{mb if mb is not None else '—'}**",
        f"- Scenario forecasts resolved: **{cb_n}**; mean Brier (multi-class sum, 0-2): "
        f"**{cb if cb is not None else '—'}**; calibration error: "
        f"**{ce if ce is not None else '—'}**",
    ]
    if "excluded" in calibration:
        lines.append("- Scenario forecasts excluded from calibration: "
                     f"{_reason_counts(calibration.get('excluded'))}")
    if binary_calibration is not None:
        bb = binary_calibration.get("mean_brier")
        bce = binary_calibration.get("calibration_error")
        lines += [
            f"- Binary forecasts scored (settlement fold, point-in-time gate): "
            f"**{binary_calibration.get('n_resolved') or 0}**; mean Brier (binary, 0-1): "
            f"**{bb if bb is not None else '—'}**; calibration error: "
            f"**{bce if bce is not None else '—'}**",
            "- Binary forecasts excluded from calibration: "
            f"{_reason_counts(binary_calibration.get('excluded'))}",
        ]
    if market_skill is not None:
        lines += _render_market_skill(market_skill)

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
    """把重报价后的行压成一条精简快照（只留价格追踪需要的字段）。

    EVAL-6：行带完整的 price_time + price_time_basis 一对（见 build_price_rows）时一并记下，
    标定 price_at_research 的取价时刻；没有或只剩半对则条目形状不变。"""
    markets = []
    for m in requoted or []:
        entry = {
            "market_id": m.get("market_id"),
            "price_at_research": _coerce_float(m.get("price_at_research")),
            "implied_yes_prob": _coerce_float(m.get("implied_yes_prob")),
            "price_delta": _coerce_float(m.get("price_delta")),
            "requote_failed": bool(m.get("requote_failed")),
        }
        _carry_price_time(m, entry)
        markets.append(entry)
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
    """生产 primary commit 行：唯一可被生产校准计分的预测目标（I-21）。
    与结算折叠共用同一谓词（forecast_ledger.is_production_primary_commit），两处永不分叉。"""
    return _ledger.is_production_primary_commit(row)


def _commit_target_meta(row: Dict[str, Any], *,
                        production_primary: bool = True) -> Dict[str, Any]:
    """账本 commit 行 → 结算用的预测原点 {as_of, created_at, commit_id, production_primary}。"""
    return {"as_of": row.get("as_of_date"), "created_at": row.get("created_at"),
            "commit_id": row.get("commit_id"), "production_primary": production_primary}


# 一份报告在生产账本与 evaluation 账本里的全部行。evaluation 类行按 Foglamp WP1 的
# record_class 重定向（forecast_ledger._route_dir）落在 evaluation_ledger_dir()；注入的非缺省
# ledger_dir 不重定向，evaluation 行就在它自己里面。两处都读才能认出 evaluation / golden 报告。
# 与人工结算（EVAL-4 load_manual_target）共用同一实现，两处永不分叉。
_report_ledger_rows = _settlement.report_ledger_rows


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


def _append_event(event: Dict[str, Any], ledger_dir: Optional[str]) -> Optional[Dict[str, Any]]:
    """把一条结算事件幂等追加进 resolutions.jsonl；重复/失败 → None。与人工结算共用
    forecast_ledger.append_settlement_event（同一基础字段拆分、幂等键与锁）。"""
    return _ledger.append_settlement_event(event, d=ledger_dir)


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
                target_meta: Optional[Dict[str, Any]] = None,
                skill_reads: Optional[MarketSkillReads] = None) -> Dict[str, Any]:
    """对一份报告跑一次解析监测。返回结果摘要 dict（供 CLI 打印/聚合）。

    可注入 forecast / report_folder / client / ledger_dir / as_of，全离线可测。
    dry_run=True 时不写任何盘（price_track / ledger / monitor_report.md 均跳过）。
    任何市场访问失败都退化为部分报告（degraded=True），绝不抛。

    EVAL-13：评估运行的预测（forecast.evaluation.record_class == 'evaluation'，或无此章而
    报告模拟属于评估运行）最先判定，直接返回 ``skipped='evaluation_run'`` 的零计数摘要，零写盘、
    零市场访问——评估运行绝不被监测，先于下面的发布闸门。

    EVAL-2：再过 fail-closed 闸门——``publishable_fn(report_id)``（缺省
    ReportManager.publishable_at_issue）为假 → ``{skipped: 'not_publishable'}``；未注入
    forecast 时只读审计封印的 forecast.json，读不到 → ``{skipped: 'not_sealed'}``；两者
    都不写盘、不联网。``as_of`` 规整为 UTC 的 processed_at（无时区按 UTC 读），是结算判定
    唯一的时钟。``target_meta``（{as_of, created_at, commit_id, production_primary}）缺省取
    target_meta_for（只认恰好预登记了本次二元预测的 commit 行）；production_primary 为
    False（非生产 primary 目标，或盘上二元预测不是 primary 预登记的那份）时结算照算照报、
    事件一律 not_production_primary，但一条也不入账（settlement.not_recorded）。
    terminal 事件照常入账，但不计入 resolved_count / newly_recorded_count /
    resolution_records，单列在 terminal_count / newly_terminal_count 与 settlement 里。

    EVAL-5（FORECAST_SKILL_SCORING）：结果与 md 另含账本范围的 market_skill
    （market_skill_summary：admissible 以 processed_at 为时钟；本报告的预测与结算所用原点
    直接传入）；``skill_reads``（MarketSkillReads）让一批 run 共享逐报告读取。"""
    processed_at = normalize_processed_at(as_of or _utcnow_iso())
    as_of_day = processed_at[:10]
    if report_folder is None:
        report_folder = _report_folder(report_id)
    _evaluation_probe = (forecast if forecast is not None
                         else _read_json(os.path.join(report_folder, "forecast.json")))
    if (is_evaluation_forecast(_evaluation_probe)
            or _report_owned_by_evaluation_run(report_folder, _EVALUATION_OWNER_MEMO)):
        # EVAL-13：评估运行的预测绝不被监测——不重报价、不入账、不落任何文件。
        skipped = _skipped_result(report_id, "evaluation_run", as_of_day, dry_run)
        skipped.update({"movers": [], "needs_manual_count": 0, "needs_manual": [],
                        "resolution_records": [], "calibration": {}, "market_brier": {},
                        "degraded": False, "monitor_report_md": ""})
        return skipped
    if not _is_publishable(report_id, publishable_fn):
        return _skipped_result(report_id, "not_publishable", as_of_day, dry_run)
    if forecast is None:
        forecast = _load_sealed_forecast(report_id)
        if forecast is None:
            return _skipped_result(report_id, "not_sealed", as_of_day, dry_run)
    thr = threshold if threshold is not None else drift_threshold()
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
    existing_events = _ledger.read_market_resolutions(ledger_dir)
    settlement = _settlement.settle_binaries(
        report_id, binaries, resolutions, target_meta=target_meta,
        processed_at=processed_at, min_equivalence=market_min_equivalence(),
        grace_days=pending_grace_days(),
        existing_events=existing_events,
        answered_market_ids=answered)
    records = [e for e in settlement["events"] if e.get("resolution_status") == "settled"]
    # 非生产 primary 目标（ensemble / what-if / comparison / revision / evaluation）：结算
    # 照算照报，但一条也不写进生产 resolutions.jsonl（I-21；键先写者赢，写错无法更正）。
    record_settlement = (target_meta or {}).get("production_primary") is not False

    # (4) 指标检查：过期却无市场判定、也无有效人工证明（EVAL-4）的预测 → 需人工判定。
    attested = {forecast_id for rid, forecast_id in _settlement.attested_items(existing_events)
                if rid == str(report_id).strip()}
    needs_manual = detect_needs_manual(binaries, resolved_ids, as_of_day, attested=attested)

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
    # EVAL-3：监测是影子可观测面——校准一律走结算折叠 + admissible() 时点闸门（报告路径另由
    # FORECAST_LEDGER_SETTLEMENT_FOLD 决定，默认不变）。
    calibration = _ledger.calibration_summary(ledger_dir, fold_settlements=True)
    binary_calibration = _ledger.binary_calibration_summary(ledger_dir)
    market_brier = _ledger.market_brier_summary(ledger_dir)
    # EVAL-5：市场相对技能（只读；FORECAST_SKILL_SCORING 关 → 结果与 md 均与此前逐字节一致）。
    market_skill: Optional[Dict[str, Any]] = None
    if skill_scoring_enabled():
        # 结算事件写入时用的预测原点（_market_event 同式：as_of 优先，否则 created_at）。
        meta = target_meta or {}
        origin = meta.get("as_of") if meta.get("as_of") not in (None, "") else meta.get("created_at")
        market_skill = _market_skill_or_error(
            ledger_dir=ledger_dir, as_of_day=as_of_day, publishable_fn=publishable_fn,
            forecasts={str(report_id).strip(): forecast},
            origins={str(report_id).strip(): origin},
            now=parse_stamp_strict(processed_at, allow_date=False), reads=skill_reads)

    md = render_monitor_md(
        report_id=report_id, as_of=as_of_day, movers=movers,
        resolution_records=records, needs_manual=needs_manual,
        calibration=calibration, market_brier=market_brier,
        anchored_count=len(anchored), degraded=degraded,
        settlement=settlement_summary,
        settlement_events=settlement["events"] + settlement["terminal"],
        binary_calibration=binary_calibration, market_skill=market_skill)

    report_path: Optional[str] = None
    if not dry_run and write_report:
        try:
            from app.utils.atomic import write_text_atomic
            report_path = os.path.join(report_folder, "monitor_report.md")
            write_text_atomic(report_path, md)
        except Exception as e:  # noqa: BLE001 — 落 md 失败不影响返回摘要
            logger.warning(f"落 monitor_report.md 失败（忽略）: {e}")
            report_path = None

    result = {
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
        "binary_calibration": binary_calibration,
        "market_brier": market_brier,
        "degraded": degraded,
        "dry_run": bool(dry_run),
        "monitor_report_path": report_path,
        "monitor_report_md": md,
    }
    if market_skill is not None:
        result["market_skill"] = market_skill
    return result


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
    结算——terminal 不需要网络。
    EVAL-4：人工证明不算入账——锚定条目照常查市场，直到市场判定或 grace terminal 关闭其
    市场通道，与人工证明不符的市场判定折叠为 conflict；持有有效（未被更正/撤回）人工证明的
    无锚点条目无需 terminal，不再可处理。"""
    recorded = _settlement.recorded_items(existing)
    attested = _settlement.attested_items(existing)
    cap = max(0, int(limit))
    overdue: List[Tuple[str, int, Dict[str, Any], List[Dict[str, Any]]]] = []
    current: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
    for position, row in enumerate(entries):
        if not _is_production_primary(row) or not str(row.get("report_id") or "").strip():
            continue
        due = _settlement.due_binaries(row.get("report_id"), row.get("binary_forecasts"),
                                       recorded, processed_at=processed_at,
                                       grace_days=grace_days, attested=attested)
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
# EVAL-5：市场相对技能（只读：结算折叠 + 读时联结锚点，绝不写 resolutions.jsonl）
# ---------------------------------------------------------------------------


def _binary_index(binaries: Any) -> Dict[str, Optional[Dict[str, Any]]]:
    """``{binary id: binary}``; an id two binaries share maps to None (it names neither)."""
    index: Dict[str, Optional[Dict[str, Any]]] = {}
    for binary in binaries if isinstance(binaries, list) else []:
        forecast_id = str(binary.get("id") or "").strip() if isinstance(binary, dict) else ""
        if forecast_id:
            index[forecast_id] = None if forecast_id in index else binary
    return index


def _registered_as(binary: Dict[str, Any], registered: Dict[str, Any]) -> bool:
    """Is ``binary`` (from forecast.json) exactly the one a commit row pre-registered
    (``forecast_ledger.compact_binary``, compared after a JSON round trip as stored)?"""
    try:
        compact = json.loads(json.dumps(_ledger.compact_binary(binary), ensure_ascii=False,
                                        allow_nan=False))
    except (TypeError, ValueError):
        return False
    return compact == registered


def _sealed_forecast_or_none(report_id: str) -> Optional[Dict[str, Any]]:
    try:
        return _load_sealed_forecast(report_id)
    except Exception as e:  # noqa: BLE001 — 读不到封印的 forecast.json → 无全量二元预测
        logger.warning(f"读取封印的 forecast.json 失败（按缺失处理）: {report_id}: {e}")
        return None


def _report_meta_origin(report_id: str) -> Optional[str]:
    """The forecast origin ``target_meta_for`` gives a report without ledger rows (pre-EVAL-1),
    which is what its settlements were written with: meta.json's ``created_at`` in UTC (no
    as-of date); None when it cannot be read."""
    try:
        folder = _report_folder(report_id)
    except Exception as e:  # noqa: BLE001 — 不可定位的报告 → 无原点（eligibility_window 读全部日期）
        logger.warning(f"定位报告目录失败（无预测原点）: {report_id}: {e}")
        return None
    meta = _read_json(os.path.join(folder, "meta.json"))
    return _local_stamp_to_utc(meta.get("created_at") if isinstance(meta, dict) else None)


class MarketSkillReads:
    """The per-report reads behind ``market_skill_summary``, each made once per report.

    ``run --all-recent N`` scores the whole ledger after each of its N reports, so every
    monitor_report.md counts the settlements appended before it: the fold over
    resolutions.jsonl is cheap and is redone each time, but the reads it joins (the sealed
    forecast.json, the publishable-at-issue proof, meta.json's creation stamp and the
    report-fallback target) do not change while a batch runs (run_monitor appends settlement
    events only), so ``_cmd_run`` shares one instance across the batch. One instance serves
    calls with the same ``publishable_fn``; a report whose forecast a call supplies itself
    (run_monitor's own) never goes through it."""

    def __init__(self) -> None:
        self._forecasts: Dict[str, Optional[Dict[str, Any]]] = {}
        self._proofs: Dict[str, bool] = {}
        self._origins: Dict[str, Optional[str]] = {}
        self._report_binaries: Dict[str, List[Dict[str, Any]]] = {}

    def sealed_forecast(self, report_id: str) -> Optional[Dict[str, Any]]:
        if report_id not in self._forecasts:
            self._forecasts[report_id] = _sealed_forecast_or_none(report_id)
        return self._forecasts[report_id]

    def proves_publishable(self, report_id: str, publishable_fn: Any) -> bool:
        if report_id not in self._proofs:
            self._proofs[report_id] = _proves_publishable_at_issue(report_id, publishable_fn)
        return self._proofs[report_id]

    def report_origin(self, report_id: str) -> Optional[str]:
        if report_id not in self._origins:
            self._origins[report_id] = _report_meta_origin(report_id)
        return self._origins[report_id]

    def report_binaries(self, report_id: str, *, ledger_dir: Optional[str],
                        publishable_fn: Any) -> List[Dict[str, Any]]:
        """``_report_fallback_binaries``, and [] for a report owned by an evaluation run
        (``_is_evaluation_report``, the check ``run --all-recent`` excludes it by): the
        monitor never settles such a report, so its binaries never leave the count."""
        if report_id not in self._report_binaries:
            binaries = _report_fallback_binaries(
                report_id, ledger_dir=ledger_dir,
                publishable_fn=lambda rid: self.proves_publishable(rid, publishable_fn),
                load_forecast_fn=self.sealed_forecast)
            if binaries and _is_evaluation_report(report_id, _EVALUATION_OWNER_MEMO):
                binaries = []
            self._report_binaries[report_id] = binaries
        return self._report_binaries[report_id]


def _report_fallback_binaries(report_id: str, *, ledger_dir: Optional[str],
                              publishable_fn: Callable[[str], Any],
                              load_forecast_fn: Callable[[str], Any]) -> List[Dict[str, Any]]:
    """The binaries of a report the monitor settles against the report itself (no production
    primary commit row: ``forecast_resolution.load_manual_target``'s report fallback, the
    same gates ``target_meta_for`` and run_monitor apply: no non-production ledger row,
    publishable at issue, a sealed forecast without an evaluation stamp); [] otherwise."""
    target, _reason = _settlement.load_manual_target(
        report_id, ledger_dir=ledger_dir, publishable_fn=publishable_fn,
        load_forecast_fn=load_forecast_fn)
    if not isinstance(target, dict) or target.get("source") != _settlement.TARGET_SOURCE_REPORT:
        return []
    return [b for b in target.get("binary_forecasts") or [] if isinstance(b, dict)]


def market_target_lookup(entries: Optional[List[Dict[str, Any]]], *,
                         forecasts: Optional[Dict[str, Any]] = None,
                         read_forecast: Optional[Callable[[str], Any]] = None
                         ) -> Callable[[str, str], Optional[Dict[str, Any]]]:
    """``lookup(report_id, forecast_id)`` → the binary forecast a settlement is scored against.

    A report with a production primary commit row (EVAL-1) is judged by the binary that row
    pre-registered (None when the row lacks it or two rows register it); its forecast.json
    binary, which also carries ``adjustment_rationale``, stands in only when it is byte for
    byte that registration. A report without one (pre-EVAL-1) falls back to the audit-sealed
    forecast.json (``read_forecast``, default ``load_structured_forecast(allow_stale_policy=
    True)``). ``forecasts`` ({report_id: forecast}) replaces that read, e.g. run_monitor's
    own forecast. Each report's forecast is read once, and only for the items looked up."""
    registered: Dict[Tuple[str, str], Optional[Dict[str, Any]]] = {}
    committed: Set[str] = set()
    for row in entries or []:
        report_id = str(row.get("report_id") or "").strip() if _is_production_primary(row) else ""
        if not report_id:
            continue
        committed.add(report_id)
        for forecast_id, binary in _binary_index(row.get("binary_forecasts")).items():
            key = (report_id, forecast_id)
            registered[key] = None if key in registered else binary
    overrides = dict(forecasts or {})
    read = read_forecast if read_forecast is not None else _sealed_forecast_or_none
    sealed: Dict[str, Dict[str, Optional[Dict[str, Any]]]] = {}

    def lookup(report_id: str, forecast_id: str) -> Optional[Dict[str, Any]]:
        rid, fid = str(report_id or "").strip(), str(forecast_id or "").strip()
        if rid not in sealed:
            forecast = overrides[rid] if rid in overrides else read(rid)
            sealed[rid] = _binary_index((forecast or {}).get("binary_forecasts")
                                        if isinstance(forecast, dict) else None)
        full = sealed[rid].get(fid)
        if rid not in committed:
            return full
        binary = registered.get((rid, fid))
        if binary is not None and full is not None and _registered_as(full, binary):
            return full
        return binary

    return lookup


def _proves_publishable_at_issue(report_id: str, publishable_fn: Any) -> bool:
    """``publishable_fn(report_id)`` (default ReportManager.publishable_at_issue) as a strict
    proof (``forecast_resolution.proves_publishable``); an error proves nothing (fail closed)."""
    fn = publishable_fn if publishable_fn is not None else _publishable_at_issue
    try:
        return _settlement.proves_publishable(fn(report_id))
    except Exception as e:  # noqa: BLE001 — 无法证明发布时可发布 → withheld
        logger.warning(f"发布状态校验失败（按 withheld 处理）: {report_id}: {e}")
        return False


def _skill_gate_reason(item: Dict[str, Any], binary: Optional[Dict[str, Any]],
                       origin: Any, now: Optional[datetime] = None) -> Optional[str]:
    """The row's ``gate_reason`` (see ``backtest.market_skill_report``) from a folded item.

    ``admissible`` (EVAL-3, the one point-in-time gate, at ``now``: default the current
    time) decides whether the outcome may be scored. The writer's equivalence reasons
    (``backtest.PROXY_GATE_REASONS``) only demote to proxy, and only when the item is
    admitted with that reason lifted; otherwise the reason that then fails
    (``not_prospective``, ``unverifiable_stamp`` ...) is returned. Every other reason
    (``conflict``, ``ambiguous_settlement``, ``unresolvable_after_grace``, ...) is returned
    as is, a non-settled item is ``not_settled`` and a market settlement for another market
    than the anchor's is ``market_mismatch``.

    The outcome label and the price it is scored against are separate facts: an admitted
    outcome (a manual attestation, or a market event the writer stopped checking at the
    equivalence step) says nothing about whether the anchor's market prices this binary's
    proposition. So the anchor whose price becomes ``market_p`` must pass
    ``forecast_resolution.market_eligibility`` with the floor at ``near`` (completeness,
    the anchor-integrity binding, and the market end date against the binary's deadline
    from the forecast ``origin`` the writer used), whatever labelled the item; the reason
    it fails with is returned (``anchor_incomplete``, ``binding_invalid``,
    ``end_date_mismatch`` ...). A headline row still needs an ``exact`` anchor
    (``backtest._skill_bucket``), so this keeps every scored row on the binary's own
    proposition and window, and a proxy row on a ``near`` one."""
    anchor = binary.get("market_anchor") if isinstance(binary, dict) else None
    anchor_market_id = str(anchor.get("market_id") or "").strip() if isinstance(anchor, dict) else ""
    ok, reason = _settlement.admissible(item, now=now)
    gate: Optional[str] = None
    if not ok and reason in _backtest.PROXY_GATE_REASONS:
        lifted_ok, lifted_reason = _settlement.admissible(
            dict(item, scoring_eligible=True, ineligible_reason=None), now=now)
        if not lifted_ok:
            return lifted_reason
        gate = reason
    elif not ok:
        return reason or "not_scoring_eligible"
    if item.get("resolution_status") != "settled":
        return "not_settled"
    if (item.get("source_kind") == _settlement.SOURCE_KIND_MARKET and anchor_market_id
            and str(item.get("market_id") or "").strip() != anchor_market_id):
        return "market_mismatch"
    if isinstance(binary, dict):
        eligible, eligibility_reason = _settlement.market_eligibility(
            binary, anchor, "near", origin=origin)
        if not eligible:
            return eligibility_reason
    return gate


def _market_skill_row(key: Tuple[str, str], item: Dict[str, Any],
                      binary: Optional[Dict[str, Any]], publishable: bool,
                      origin: Any = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """One folded item + its target binary → a ``backtest.market_skill_report`` row.
    ``market_p`` is derived exactly as the settlement writer stamps ``market_p_at_research``
    (``forecast_resolution._market_price_at_research``: a finite price_at_research, else a
    finite implied_yes_prob)."""
    anchor = binary.get("market_anchor") if isinstance(binary, dict) else None
    anchor = anchor if isinstance(anchor, dict) else {}
    market_id = str(anchor.get("market_id") or "").strip()
    if isinstance(binary, dict) and not market_id:
        gate: Optional[str] = "no_market_anchor"
    else:
        gate = _skill_gate_reason(item, binary, origin, now)
    outcome = str(item.get("outcome") or "").strip().upper()
    market_p = _settlement._market_price_at_research(anchor)
    basis: Optional[str] = None
    if all(isinstance(anchor.get(k), str) and anchor[k].strip() for k in _PRICE_TIME_KEYS):
        basis = anchor["price_time_basis"]
    influence = binary.get("market_influence") if isinstance(binary, dict) else None
    prior: Optional[float] = None
    if (isinstance(influence, dict) and market_id
            and str(influence.get("market_id") or "").strip() == market_id
            and influence.get("probability_restored") is not True):
        prior = _coerce_float(influence.get("prior_probability"))
    cites: Optional[bool] = None
    if isinstance(binary, dict) and "adjustment_rationale" in binary:
        # An implied_yes_prob that is no probability (a corrupt or hand-edited forecast.json,
        # e.g. inf) is left out, as the extractor skips an unparseable one: the check then
        # rests on the keywords alone and never raises out of the ledger-wide block.
        price = _settlement._finite(anchor.get("implied_yes_prob"))
        cited = (anchor if price is not None and 0.0 <= price <= 1.0
                 else {k: v for k, v in anchor.items() if k != "implied_yes_prob"})
        cites = _extractor._rationale_cites_market(binary.get("adjustment_rationale"), cited)
    equivalence = str(anchor.get("resolution_equivalence") or "").strip().lower()
    return {
        "report_id": key[0],
        "forecast_id": key[1],
        "y": {"YES": 1, "NO": 0}.get(outcome),
        "model_p": item.get("model_p"),
        "market_p": market_p,
        "equivalence": equivalence or None,
        "match_confidence": _coerce_float(anchor.get("match_confidence")),
        "publishable_at_issue": publishable,
        "rationale_cites_market": cites,
        "prior_probability": prior,
        "price_time_basis": basis,
        "gate_reason": gate,
    }


# EVAL-5: the gate reason of a folded item whose skill row could not be built (a target or
# anchor the row builder raised on): counted in unscored, never scored, and never allowed
# to blank the ledger-wide block.
UNREADABLE_SKILL_ROW = "row_unreadable"


def _unreadable_skill_row(key: Tuple[str, str], publishable: bool) -> Dict[str, Any]:
    """The ``backtest.market_skill_report`` row of an item ``_market_skill_row`` raised on."""
    return {"report_id": key[0], "forecast_id": key[1], "y": None, "model_p": None,
            "market_p": None, "equivalence": None, "match_confidence": None,
            "publishable_at_issue": publishable, "rationale_cites_market": None,
            "prior_probability": None, "price_time_basis": None,
            "gate_reason": UNREADABLE_SKILL_ROW}


def _primary_report_ids(targets: Optional[List[Dict[str, Any]]]) -> Set[str]:
    """Report ids with a production primary commit row (EVAL-1) in ``targets``."""
    return {str(row.get("report_id") or "").strip() for row in targets or []
            if _is_production_primary(row)} - {""}


def _registered_origins(targets: Optional[List[Dict[str, Any]]]
                        ) -> Dict[Tuple[str, str], Any]:
    """``{(report_id, binary id): forecast origin}`` over the production primary commit rows
    of ``targets``: the as-of date, else the creation stamp, as the settlement writer reads
    them; a binary two rows register maps to None (``eligibility_window`` then reads every
    date the binary names)."""
    origins: Dict[Tuple[str, str], Any] = {}
    for row in targets or []:
        report_id = str(row.get("report_id") or "").strip() if _is_production_primary(row) else ""
        if not report_id:
            continue
        as_of = row.get("as_of_date")
        origin = as_of if as_of not in (None, "") else row.get("created_at")
        for forecast_id in _binary_index(row.get("binary_forecasts")):
            key = (report_id, forecast_id)
            origins[key] = None if key in origins else origin
    return origins


def enrich_market_rows(resolution_rows: Optional[List[Dict[str, Any]]], *,
                       target_lookup: Callable[[str, str], Optional[Dict[str, Any]]],
                       publishable_fn: Any = None,
                       targets: Optional[List[Dict[str, Any]]] = None,
                       origin_fn: Optional[Callable[[str], Any]] = None,
                       now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """``backtest.market_skill_report`` rows from the settlement events, one per folded item.

    Pure apart from the injected callables: the scored set is
    ``forecast_resolution.fold_binary_items(resolution_rows, targets)`` (EVAL-3/4: one item
    per (report_id, forecast_id); superseded and retracted attestations removed; disagreeing
    eligible events a ``conflict``; legacy rows proven only against ``targets``), never the
    raw event lines, so each item counts once. ``target_lookup(report_id, forecast_id)``
    (see ``market_target_lookup``) gives the binary whose anchor supplies ``market_p``
    (price_at_research, else implied_yes_prob, as the writer derives it), ``equivalence``,
    ``match_confidence`` and ``price_time_basis``; ``prior_probability`` comes from a
    ``market_influence`` stamp of that anchor's market that was not rolled back,
    ``rationale_cites_market`` from ``forecast_extractor._rationale_cites_market`` (None
    without a rationale). A binary without a market anchor is ``no_market_anchor``; every
    other item is gated by ``_skill_gate_reason``: ``admissible`` at ``now`` (default the
    current time) for the outcome, and ``market_eligibility`` at the ``near`` floor for the
    anchor, from the forecast origin the writer used: the one its production primary
    commit row in ``targets`` registers, else, for a report without such a row
    (pre-EVAL-1), ``origin_fn(report_id)`` (meta.json's creation stamp, as
    ``target_meta_for`` reads it; without ``origin_fn`` every date the binary names counts).
    ``publishable_at_issue`` is the item's events' ``report_publishable_at_issue`` stamps
    (EVAL-2: all must be True), else a strict ``publishable_fn(report_id)`` proof, once per
    report. An item whose target lookup or row raises is logged and kept as an
    ``UNREADABLE_SKILL_ROW`` row (unscored), so one corrupt target never fails the others.
    Rows are sorted by key; neither the inputs nor resolutions.jsonl are ever modified.
    """
    events = [row for row in resolution_rows or [] if isinstance(row, dict)]
    stamps: Dict[Tuple[str, str], List[Any]] = {}
    for event in events:
        if "report_publishable_at_issue" in event:
            key = (str(event.get("report_id") or "").strip(),
                   str(event.get("forecast_id") or "").strip())
            stamps.setdefault(key, []).append(event["report_publishable_at_issue"])
    items = _settlement.fold_binary_items(events, targets)
    origins = _registered_origins(targets)
    committed = _primary_report_ids(targets)
    report_origins: Dict[str, Any] = {}
    proofs: Dict[str, bool] = {}
    rows: List[Dict[str, Any]] = []
    for key in sorted(items):
        if key in stamps:
            publishable = all(stamp is True for stamp in stamps[key])
        else:
            if key[0] not in proofs:
                proofs[key[0]] = _proves_publishable_at_issue(key[0], publishable_fn)
            publishable = proofs[key[0]]
        if key[0] in committed or origin_fn is None:
            origin = origins.get(key)
        else:
            if key[0] not in report_origins:
                report_origins[key[0]] = origin_fn(key[0])
            origin = report_origins[key[0]]
        try:
            binary = target_lookup(key[0], key[1])
            row = _market_skill_row(key, items[key], binary if isinstance(binary, dict)
                                    else None, publishable, origin, now)
        except Exception as e:  # noqa: BLE001 — 一行读不出只记这一行为未计分，不拖垮整块评分
            logger.warning(f"市场技能评分行读取失败（计为 {UNREADABLE_SKILL_ROW}）: {key}: {e}")
            row = _unreadable_skill_row(key, publishable)
        rows.append(row)
    return rows


def expired_unresolved_count(entries: Optional[List[Dict[str, Any]]],
                             settled_keys: Set[Tuple[str, str]], as_of_day: str, *,
                             report_binaries: Optional[Dict[str, Any]] = None) -> int:
    """Market-anchored binaries whose resolution date has passed (``detect_needs_manual``
    with ``has_anchor``) and that hold no settlement fact of any kind yet (``settled_keys``:
    the folded items). They sit outside every stratum until their market settles or their
    grace terminal is written, so they are counted, not dropped. The binaries are those of
    the production primary commit rows in ``entries`` plus ``report_binaries``
    ({report_id: binaries}) of reports without such a row (pre-EVAL-1), which the monitor
    settles against the report itself; a report with a commit row is read from that row
    only, and each (report_id, binary id) counts once."""
    committed = _primary_report_ids(entries)
    sources: List[Tuple[str, Any]] = [
        (str(row.get("report_id") or "").strip(), row.get("binary_forecasts"))
        for row in entries or [] if _is_production_primary(row)]
    sources += [(str(report_id or "").strip(), binaries)
                for report_id, binaries in sorted((report_binaries or {}).items())
                if str(report_id or "").strip() not in committed]
    seen: Set[Tuple[str, str]] = set()
    count = 0
    for report_id, binaries in sources:
        if not report_id:
            continue
        open_binaries: List[Dict[str, Any]] = []
        for forecast_id, binary in _binary_index(binaries).items():
            key = (report_id, forecast_id)
            if binary is not None and key not in settled_keys and key not in seen:
                seen.add(key)
                open_binaries.append(binary)
        count += sum(1 for need in detect_needs_manual(open_binaries, set(), as_of_day)
                     if need.get("has_anchor"))
    return count


def market_skill_summary(ledger_dir: Optional[str] = None, *, as_of_day: Optional[str] = None,
                         publishable_fn: Any = None,
                         forecasts: Optional[Dict[str, Any]] = None,
                         origins: Optional[Dict[str, Any]] = None,
                         now: Optional[datetime] = None,
                         reads: Optional[MarketSkillReads] = None) -> Dict[str, Any]:
    """``market_skill`` of the run_monitor result / monitor_report.md and of ``summary``:
    ``backtest.market_skill_report`` over the ledger's folded binary settlements
    (``enrich_market_rows``), at FORECAST_SKILL_MIN_N and the 10pp rule's
    FORECAST_MARKET_DIVERGENCE_MIN_CONFIDENCE, plus ``expired_unresolved`` as of
    ``as_of_day`` (default the UTC day of ``now``).

    ``now`` (offset-aware; default the current time) is the point-in-time clock of the
    ``admissible`` gate: run_monitor passes its processed_at, so a backdated run scores only
    what was known by then. ``forecasts`` ({report_id: forecast}) and ``origins``
    ({report_id: forecast origin}) are run_monitor's own forecast and the origin it settled
    with; any other report without a production primary commit row (pre-EVAL-1) is read
    from its sealed forecast.json and meta.json, and counts in ``expired_unresolved`` when
    the monitor settles it against the report itself (``_report_fallback_binaries``).
    ``reads`` (default a fresh ``MarketSkillReads``) memoizes those per-report reads.
    Reads resolutions.jsonl, ledger.jsonl and report files only; never writes."""
    reads = reads if reads is not None else MarketSkillReads()
    overrides = {str(rid).strip(): forecast for rid, forecast in (forecasts or {}).items()}
    given_origins = {str(rid).strip(): origin for rid, origin in (origins or {}).items()}
    day = as_of_day or (now.astimezone(timezone.utc).date().isoformat() if now else _today())
    events = _ledger.read_market_resolutions(ledger_dir)
    entries = _ledger.read_ledger(ledger_dir)

    def proves_publishable(report_id: str) -> bool:
        return reads.proves_publishable(report_id, publishable_fn)

    def origin_of(report_id: str) -> Any:
        if report_id in given_origins:
            return given_origins[report_id]
        return reads.report_origin(report_id)

    rows = enrich_market_rows(
        events, targets=entries, publishable_fn=proves_publishable, origin_fn=origin_of,
        now=now, target_lookup=market_target_lookup(entries, forecasts=overrides,
                                                     read_forecast=reads.sealed_forecast))
    report = _backtest.market_skill_report(rows, min_n=skill_min_n(),
                                           min_match_confidence=divergence_min_confidence())
    committed = _primary_report_ids(entries)
    legacy_ids = {str(row.get("report_id") or "").strip()
                  for row in events + entries if isinstance(row, dict)}
    report_binaries: Dict[str, List[Dict[str, Any]]] = {}
    for report_id in sorted((legacy_ids | set(overrides)) - committed - {""}):
        if report_id in overrides:
            report_binaries[report_id] = _report_fallback_binaries(
                report_id, ledger_dir=ledger_dir, publishable_fn=proves_publishable,
                load_forecast_fn=lambda _rid, forecast=overrides[report_id]: forecast)
        else:
            report_binaries[report_id] = reads.report_binaries(
                report_id, ledger_dir=ledger_dir, publishable_fn=publishable_fn)
    report["as_of"] = day
    report["expired_unresolved"] = expired_unresolved_count(
        entries, {(row["report_id"], row["forecast_id"]) for row in rows}, day,
        report_binaries=report_binaries)
    return report


def _market_skill_or_error(**kwargs: Any) -> Dict[str, Any]:
    """``market_skill_summary`` that never raises: an enhancement must not break the monitor."""
    try:
        return market_skill_summary(**kwargs)
    except Exception as e:  # noqa: BLE001 — 技能评分失败只记日志，不影响监测
        logger.warning(f"市场相对技能评分失败（跳过）: {e}")
        return {"schema": _backtest.MARKET_SKILL_SCHEMA, "error": str(e)}


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

    sub.add_parser("summary", help="打印账本里的持续 Brier / 校准（无网络；EVAL-5 另含 market_skill）")

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
    # EVAL-5：一批报告共享逐报告读取（封印预测 / 发布证明 / meta 原点），每份报告只读一次。
    skill_reads = MarketSkillReads()
    for rid in report_ids:
        try:
            res = run_monitor(rid, dry_run=dry, skill_reads=skill_reads)
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
        payload: Dict[str, Any] = {
            "market_brier": _ledger.market_brier_summary(),
            "scenario_calibration": _ledger.calibration_summary(fold_settlements=True),
            "binary_calibration": _ledger.binary_calibration_summary(),
        }
        if skill_scoring_enabled():
            payload["market_skill"] = _market_skill_or_error()
        _print_json(payload)
        return 0
    return 2  # 不可达（subparser required）


if __name__ == "__main__":
    raise SystemExit(main())
