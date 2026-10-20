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
import calendar
import hashlib
import json
import math
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
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


# 判定标准里显式写出的 ISO 日期（如「by 2026-11-03」）优先于 horizon_year 年底代理。
_ISO_DATE_RE = re.compile(r"(?<!\d)(20\d{2}-\d{2}-\d{2})(?!\d)")


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


def _data_period_bounds(value: Any) -> Optional[tuple[str, str]]:
    """Only exact supported periods can trigger a bounded provider query."""
    text = str(value or "").strip()
    try:
        if re.fullmatch(r"\d{4}", text):
            year = int(text)
            return date(year, 1, 1).isoformat(), date(year, 12, 31).isoformat()
        quarter = re.fullmatch(r"(\d{4})-Q([1-4])", text)
        if quarter:
            year, q = int(quarter[1]), int(quarter[2])
            start_month, end_month = 3 * q - 2, 3 * q
            return (date(year, start_month, 1).isoformat(),
                    date(year, end_month, calendar.monthrange(year, end_month)[1]).isoformat())
        if re.fullmatch(r"\d{4}-\d{2}", text):
            year, month = map(int, text.split("-"))
            return date(year, month, 1).isoformat(), date(year, month, calendar.monthrange(year, month)[1]).isoformat()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            value = date.fromisoformat(text).isoformat()
            return value, value
    except ValueError:
        pass
    return None


def _anchor_period_bounds(anchor: Dict[str, Any]) -> Optional[tuple[str, str]]:
    """A validated anchor stores its canonical period start and the series frequency;
    the whole period (an annual '2026-01-01' is the full year) bounds the query, so
    the fetch waits until that period has ended. Other anchors use their text."""
    period = str(anchor.get("period") or "").strip()
    frequency = str(anchor.get("frequency") or "").strip().upper()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", period) and frequency in ("D", "W", "M", "Q", "A"):
        try:
            start = date.fromisoformat(period)
            if frequency in ("D", "W"):
                end = start + timedelta(days=0 if frequency == "D" else 6)
            else:
                months = start.month - 1 + {"M": 1, "Q": 3, "A": 12}[frequency]
                end = date(start.year + months // 12, months % 12 + 1, 1) - timedelta(days=1)
            return start.isoformat(), end.isoformat()
        except ValueError:
            return None
    return _data_period_bounds(anchor.get("observation") or anchor.get("period"))


# Days after a period ends during which a missing official value is ordinary
# publication lag (pending); past this window it needs manual review.
_PUBLICATION_GRACE_DAYS = {"D": 30, "W": 30, "M": 120, "Q": 210, "A": 730}


def _unusable_fetch_status(fetched: Any, period_end: str, frequency: str, as_of: Optional[str]) -> Dict[str, str]:
    """Status for a fetch without a usable series (normally the data layer's DataError).

    A transient source failure, or an ended period the provider has no value for yet,
    stays pending and is retried on the next run; any other failure, or a value still
    missing after the publication grace window, needs manual review."""
    code = str(getattr(fetched, "code", "") or "")
    if getattr(fetched, "retryable", False) is True:
        return {"status": "pending", "reason": f"Official source temporarily unavailable ({code}); retried on the next run"}
    if code in ("not_found", "invalid_window"):
        grace = _PUBLICATION_GRACE_DAYS.get(str(frequency or "").upper(), _PUBLICATION_GRACE_DAYS["M"])
        try:
            cutoff = date.fromisoformat(str(as_of if as_of is not None else _utcnow_iso())[:10])
            overdue = cutoff > date.fromisoformat(period_end) + timedelta(days=grace)
        except ValueError:
            overdue = True
        if not overdue:
            return {"status": "pending", "reason": "Official value for the period is not yet published"}
        return {"status": "manual", "reason": f"Official value still unpublished {grace} days after the period ended"}
    return {"status": "manual",
            "reason": "Provider did not return a usable official series" + (f" ({code})" if code else "")}


def resolve_official_forecasts(binaries, *, report_id, as_of, already_resolved=(), data_client=None,
                              dry_run=False):
    """Resolve an exact period; None means current time after each retrieval."""
    from app.services import official_data
    records, statuses = [], []
    if not getattr(Config, "DATA_SOURCES_ENABLED", False):
        return records, statuses
    skipped = {str(fid).strip() for fid in already_resolved}
    for binary in binaries:
        anchor = binary.get("data_anchor")
        fid = str(binary.get("id") or "").strip()
        if not isinstance(anchor, dict) or fid in skipped:
            continue
        identity = str(anchor.get("series") or "").strip()
        status = {"forecast_id": fid, "series": identity, "status": "manual", "reason": "Invalid data anchor"}
        bounds = _anchor_period_bounds(anchor)
        if not fid or not identity or bounds is None:
            statuses.append(status)
            continue
        if bounds[1] > str(as_of if as_of is not None else _utcnow_iso())[:10]:
            status.update(status="pending", reason="Observation period has not ended")
            statuses.append(status)
            continue
        if dry_run:
            # Official adapters maintain disk caches/quotas and may start MCP
            # processes. Preserve the monitor's no-write dry-run guarantee.
            status.update(status="pending", reason="Dry run: official source fetch not performed", attempted=False)
            statuses.append(status)
            continue
        try:
            if data_client is None:
                data_client = official_data.get_data_sources()
            if data_client is None:
                status["reason"] = "Official data unavailable"
                statuses.append(status)
                continue
            fetched = data_client.get(identity, start=bounds[0], end=bounds[1],
                                      transform=str(anchor.get("transform") or ""), max_obs=240)
            payload = fetched.to_dict() if hasattr(fetched, "to_dict") else fetched
            if not isinstance(payload, dict) or not isinstance(payload.get("observations"), list):
                status.update(_unusable_fetch_status(fetched, bounds[1], str(anchor.get("frequency") or ""), as_of))
                statuses.append(status)
                continue
            # A current-time check must include the retrieval it just performed.
            # Explicit historical cutoffs never move as a consequence of fetching.
            resolution_cutoff = as_of if as_of is not None else _utcnow_iso()
            decision = official_data.resolve_data_anchor(anchor, fetched, as_of=resolution_cutoff)
            if not isinstance(decision, dict):
                raise ValueError("Invalid resolution response")
            status.update(status=decision.get("status", "manual"), reason=str(decision.get("reason") or "")[:300])
            if status["status"] not in {"resolved", "pending", "manual"}:
                status.update(status="manual", reason="Invalid official resolution status")
            probability = _coerce_float(binary.get("probability"))
            if (status["status"] == "resolved" and type(decision.get("outcome")) is bool
                    and isinstance(decision.get("observation"), dict)
                    and probability is not None and math.isfinite(probability) and 0 <= probability <= 1):
                encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                records.append({
                    "report_id": report_id, "forecast_id": fid, "series": identity,
                    "resolved_outcome": decision["outcome"], "model_p": probability,
                    "brier_contribution": round((probability - float(decision["outcome"])) ** 2, 4),
                    "resolved_at": resolution_cutoff, "observation": decision["observation"],
                    "units": payload.get("units"), "transform": payload.get("transform", ""),
                    "source_url": payload.get("source_url"), "retrieved_at": payload.get("retrieved_at"),
                    "vintage": payload.get("vintage", ""), "data_anchor": dict(anchor),
                    "dataset_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                    "dataset_snapshot": json.loads(encoded),
                })
            elif status["status"] == "resolved":
                status.update(status="manual", reason="Incomplete outcome or model probability")
        except Exception as exc:  # source outage preserves a pending/manual outcome
            status.update(status="manual", reason=f"Official data unavailable ({type(exc).__name__})")
        statuses.append(status)
    return records, statuses


def _recorded_official_outcomes(binaries, previous, *, report_id, as_of):
    """A recorded outcome is immutable and cannot leak into an earlier cutoff."""
    from app.services import official_data
    rows = {(str(row.get("forecast_id") or "").strip(), str(row.get("series") or "").strip()): row
            for row in previous if str(row.get("report_id") or "").strip() == str(report_id).strip()}
    records, statuses, seen = [], [], set()
    keys = ("series", "comparator", "threshold", "period", "transform", "units")
    for binary in binaries:
        anchor = binary.get("data_anchor")
        if not isinstance(anchor, dict):
            continue
        fid, sid = str(binary.get("id") or "").strip(), str(anchor.get("series") or "").strip()
        prior = rows.get((fid, sid))
        if prior is None:
            continue
        seen.add(fid)
        status = {"forecast_id": fid, "series": sid, "status": "manual",
                  "reason": "Recorded outcome differs from the current forecast contract"}
        try:
            snapshot = prior.get("dataset_snapshot")
            encoded = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            if hashlib.sha256(encoded.encode("utf-8")).hexdigest() != prior.get("dataset_sha256"):
                raise ValueError("Recorded dataset hash mismatch")
            carrier = {"series": [snapshot]}
            original = official_data.validate_data_anchor(prior.get("data_anchor"), carrier)
            current = official_data.validate_data_anchor(anchor, carrier)
            probability = _coerce_float(binary.get("probability"))
            if (not original or not current or any(original[key] != current[key] for key in keys)
                    or probability is None or not math.isfinite(probability) or not 0 <= probability <= 1
                    or prior.get("model_p") != probability):
                raise ValueError("Recorded forecast contract mismatch")
            recorded_at = official_data.resolution_instant(prior.get("resolved_at"))
            cutoff = official_data.resolution_instant(as_of)
            if recorded_at > cutoff:
                status.update(status="pending", reason="Recorded outcome was unavailable at the requested cutoff")
            else:
                # Revalidate the sealed snapshot under the same eligibility rules
                # as a fresh observation. Never refetch a revised provider value.
                decision = official_data.resolve_data_anchor(anchor, snapshot, as_of=prior.get("resolved_at"))
                if (decision.get("status") != "resolved"
                        or type(prior.get("resolved_outcome")) is not bool
                        or decision.get("outcome") != prior["resolved_outcome"]
                        or decision.get("observation") != prior.get("observation")):
                    raise ValueError("Recorded outcome does not match its snapshot")
                record = dict(prior, report_id=str(report_id).strip(), forecast_id=fid, series=sid)
                record["brier_contribution"] = round((probability - float(prior["resolved_outcome"])) ** 2, 4)
                records.append(record)
                status.update(status="resolved", reason="Previously recorded official outcome; original observation retained")
        except (TypeError, ValueError, KeyError, OverflowError):
            pass  # malformed or obsolete evidence requires manual adjudication
        statuses.append(status)
    return records, statuses, seen


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
                write_report: bool = True, data_client: Any = None) -> Dict[str, Any]:
    """对一份报告跑一次解析监测。返回结果摘要 dict（供 CLI 打印/聚合）。

    可注入 forecast / report_folder / client / ledger_dir / as_of，全离线可测。
    dry_run=True 时不写任何盘（price_track / ledger / monitor_report.md 均跳过）。
    任何市场访问失败都退化为部分报告（degraded=True），绝不抛。"""
    current_time = as_of is None
    as_of = _utcnow_iso() if current_time else as_of
    as_of_day = str(as_of)[:10]
    thr = threshold if threshold is not None else drift_threshold()
    if report_folder is None:
        report_folder = _report_folder(report_id)
    if forecast is None:
        forecast = _read_json(os.path.join(report_folder, "forecast.json"))
    if isinstance(forecast, dict) and isinstance(forecast.get("backtest"), dict):
        # A backtest report forecasts a question whose outcome is already known:
        # it is scored by backend/scripts/backtest_eval.py, never by this monitor
        # (no re-quote, no price track, no market or data resolution rows).
        return {"report_id": report_id, "as_of": as_of, "skipped": "backtest", "anchored_count": 0,
                "resolved_count": 0, "newly_recorded_count": 0, "needs_manual_count": 0,
                "degraded": False, "dry_run": bool(dry_run), "monitor_report_path": None}
    if client is None:
        from app.utils.prediction_markets import PolymarketClient
        client = PolymarketClient()

    binaries = [dict(b, id=str(b.get("id") or "").strip()) for b in ((forecast or {}).get("binary_forecasts") or [])
                if isinstance(b, dict)]
    anchored = anchored_forecasts(dict(forecast or {}, binary_forecasts=binaries))
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

    prior_data, prior_statuses, prior_ids = _recorded_official_outcomes(
        binaries, _ledger.read_data_resolutions(ledger_dir), report_id=report_id, as_of=as_of,
    ) if getattr(Config, "DATA_SOURCES_ENABLED", False) else ([], [], set())
    # Preserve the first official resolution rather than scoring this forecast
    # a second time when a market subsequently reaches its terminal state.
    records = [row for row in records if str(row.get("forecast_id") or "") not in prior_ids]
    data_records, data_statuses = resolve_official_forecasts(
        binaries, report_id=report_id, as_of=None if current_time else as_of,
        already_resolved=[row.get("forecast_id") for row in records] + list(prior_ids),
        data_client=data_client, dry_run=dry_run,
    )
    data_records = prior_data + data_records
    data_statuses = prior_statuses + data_statuses
    if current_time:
        as_of = _utcnow_iso()
        as_of_day = str(as_of)[:10]
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
        for rec in data_records:
            written = _ledger.append_data_resolution(rec, d=ledger_dir)
            if written is not None:
                newly_recorded.append(written)
        if data_statuses:
            # The append lock can choose another monitor's row. Apply exactly
            # the replay contract/cutoff validation to that committed winner.
            committed, committed_statuses, _ = _recorded_official_outcomes(
                binaries, _ledger.read_data_resolutions(ledger_dir), report_id=report_id, as_of=as_of)
            committed_keys = {(row["forecast_id"], row["series"]) for row in committed_statuses}
            for row in data_statuses:
                if row["status"] == "resolved" and (row["forecast_id"], row["series"]) not in committed_keys:
                    row.update(status="manual", reason="Official outcome was not durably recorded")
            data_statuses = [row for row in data_statuses
                             if (row["forecast_id"], row["series"]) not in committed_keys] + committed_statuses
            data_records = committed

    # Compute presentation and counts only after the committed evidence wins.
    data_resolved_ids = {row["forecast_id"] for row in data_records}
    data_pending_ids = {row["forecast_id"] for row in data_statuses if row["status"] == "pending"}
    data_manual = {row["forecast_id"]: row for row in data_statuses if row["status"] == "manual"}
    degraded = degraded or bool(data_manual)
    needs_manual = detect_needs_manual(binaries, resolved_ids, as_of_day)
    needs_manual = [row for row in needs_manual
                    if row.get("forecast_id") not in data_resolved_ids | data_pending_ids]
    for row in needs_manual:
        if row.get("forecast_id") in data_manual:
            row["reason"] = data_manual[row["forecast_id"]]["reason"]

    # ── 汇总分数（账本读取；dry-run 也能读，只是不含本次未写入的新判定）──
    calibration = _ledger.calibration_summary(ledger_dir)
    market_brier = _ledger.market_brier_summary(ledger_dir)
    data_brier = _ledger.data_brier_summary(ledger_dir) if data_statuses else {"n_resolved": 0, "mean_brier": None}

    md = render_monitor_md(
        report_id=report_id, as_of=as_of_day, movers=movers,
        resolution_records=records, needs_manual=needs_manual,
        calibration=calibration, market_brier=market_brier,
        anchored_count=len(anchored), degraded=degraded)
    if data_statuses:
        lines = ["", "## Official data outcomes", "",
                 "| Forecast | Series | Status | Evidence |", "|---|---|---|---|"]
        by_id = {row["forecast_id"]: row for row in data_records}
        for row in data_statuses:
            record = by_id.get(row["forecast_id"])
            if record:
                obs = record["observation"]
                evidence = f"{obs.get('value')} {record.get('units') or ''} ({obs.get('date')}); Brier {record['brier_contribution']}"
            else:
                evidence = row["reason"]
            lines.append(f"| {_cell(row['forecast_id'])} | {_cell(row['series'])} | {_cell(row['status'])} | {_cell(evidence)} |")
        md += "\n".join(lines) + "\n"

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
        "anchored_count": len(anchored),
        "movers": movers,
        "resolved_count": len(records) + len(data_records),
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
    if data_statuses:
        result.update(data_resolution_records=data_records,
                      data_resolution_status=data_statuses, data_brier=data_brier)
    return result


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _summary_row(res: Dict[str, Any]) -> Dict[str, Any]:
    """把 run_monitor 的完整结果压成一行便于聚合打印（去掉大字段）。

    带官方数据锚的报告另附 data_* 计数（resolved / pending / manual），无锚时行不变。"""
    row = {
        "report_id": res.get("report_id"),
        **({"skipped": res["skipped"]} if res.get("skipped") else {}),
        "anchored": res.get("anchored_count"),
        "movers": len(res.get("movers") or []),
        "resolved": res.get("resolved_count"),
        "newly_recorded": res.get("newly_recorded_count"),
        "needs_manual": res.get("needs_manual_count"),
        "degraded": res.get("degraded"),
        "monitor_report": res.get("monitor_report_path"),
    }
    statuses = res.get("data_resolution_status")
    if isinstance(statuses, list):
        for status in ("resolved", "pending", "manual"):
            row[f"data_{status}"] = sum(1 for item in statuses
                                        if isinstance(item, dict) and item.get("status") == status)
    return row


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
            # Official-data outcomes (data_resolutions.jsonl) stay a separate track record.
            "official_data_brier": _ledger.data_brier_summary(),
        })
        return 0
    return 2  # 不可达（subparser required）


if __name__ == "__main__":
    raise SystemExit(main())
