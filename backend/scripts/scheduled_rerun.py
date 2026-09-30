"""定时重跑 + 漂移检测（I-9-6）

把一次性的预测报告变成「持续态势监测」：周期性地重跑一份**已保存的预测定义**
（prompt + depth + options），并把每一份新预测与上一份对比，标记出实质性漂移
（某情景概率移动超过阈值、出现新的主导角色/联盟）。每次运行都链回上一次运行，
便于 UI 展示「预测如何随时间演化」的时间线，并把漂移高亮出来。可选地在漂移超阈值
时 POST 一个 webhook 摘要。

设计要点
--------
* 调度定义持久化在 ``uploads/schedules/<id>/schedule.json``（与 pipelines/reports
  同目录约定 + 原子写）。形如：
    {schedule_id, prompt, depth, options, interval_minutes, last_run_at,
     next_run_at, run_pipeline_ids:[...], enabled, max_runs, ...}
* 守护线程（``Scheduler``，与 SimulationRunner 的 monitor 线程同构）每隔
  SCHEDULER_TICK_SECONDS 扫描一遍调度，对任何「到点 + enabled + 未达上限」的调度
  调用 ``PipelineOrchestrator.start(prompt, ...)``，追加 pipeline_id、更新
  next_run_at。
* 漂移检测复用既有结构化预测 forecast.json（forecast_extractor 产物）：按情景名
  匹配，``delta=|curr.p - prev.p|``，超过 DRIFT_PROB_THRESHOLD 即标记；并对调研
  档案（actors.json）与图谱联盟（communities.json）的 top 角色/联盟做集合差。
* **完全可降级**：守护进程只在 SCHEDULER_ENABLED=true 时启动；不启动即对现有
  行为零影响（不起线程、不改任何管线语义）。所有 Config 旋钮均经
  ``getattr(Config, NAME, default)`` 读取，故本文件不依赖 config.py 是否登记这些键。

崩溃恢复
--------
* next_run_at 持久化 → 重启后从断点继续；幂等 due-check：若该调度已有一条在飞管线
  （PipelineManager 记录里 status==running 且 pipeline_id 仍在调度的 run 列表中），
  本 tick 跳过，避免重复触发（与 reconcile_orphans 配合）。
* 全局并发上限（SCHEDULER_MAX_CONCURRENT）防止某条慢运行把后续 tick 堆叠成多条
  并行管线、静默烧额度。

命令行
------
    python scripts/scheduled_rerun.py add  --prompt "…" --interval-minutes 360 [--depth deep] [--max-runs 20]
    python scripts/scheduled_rerun.py list
    python scripts/scheduled_rerun.py show    <schedule_id>
    python scripts/scheduled_rerun.py enable  <schedule_id>
    python scripts/scheduled_rerun.py disable <schedule_id>
    python scripts/scheduled_rerun.py delete  <schedule_id>
    python scripts/scheduled_rerun.py run-once <schedule_id>   # 立即触发一次（忽略 next_run_at）
    python scripts/scheduled_rerun.py tick                     # 跑一遍 due-check 后退出（适合外部 cron）
    python scripts/scheduled_rerun.py daemon                   # 常驻守护线程（需 SCHEDULER_ENABLED=true）
    python scripts/scheduled_rerun.py diff <pipe_a> <pipe_b>   # 打印两条管线预测的漂移报告
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from urllib import error as _urlerror
from urllib import request as _urlrequest

# ── 让脚本无论从哪个 cwd 调用都能 import 到 backend 的 app 包 ──
# scripts/ 在 backend/ 下；把 backend/ 放到 sys.path 头部（与 export_demo_site_data.py 一致）。
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.config import Config  # noqa: E402
from app.config_audit import parse_int_option  # noqa: E402
from app.services.ensemble import _norm_name  # noqa: E402 — 复用情景名归一化，保证 diff 与集成口径一致
from app.services.pipeline_orchestrator import (  # noqa: E402
    PipelineManager,
    PipelineOrchestrator,
)
from app.services.report_agent import ReportManager  # noqa: E402
from app.utils.atomic import write_json_atomic  # noqa: E402
from app.utils.logger import get_logger  # noqa: E402

logger = get_logger("mirofish.scheduler")


# ---------------------------------------------------------------------------
# Config 旋钮（默认全部「关 / 现状」；经 getattr 读取，本文件不拥有 config.py）
# ---------------------------------------------------------------------------
# 在 backend/app/config.py 的 Config 中登记以下键即可让它们出现在设置/校验里；
# 未登记时本文件用下方默认值，行为不变。
#
#   SCHEDULER_ENABLED            = os.environ.get('SCHEDULER_ENABLED', 'False')...== 'true'   # 守护线程总开关（默认关）
#   SCHEDULER_TICK_SECONDS       = int(os.environ.get('SCHEDULER_TICK_SECONDS', '60'))        # due-check 间隔
#   SCHEDULER_MAX_CONCURRENT     = int(os.environ.get('SCHEDULER_MAX_CONCURRENT', '1'))       # 全局并发上限
#   SCHEDULER_DEFAULT_MAX_RUNS   = int(os.environ.get('SCHEDULER_DEFAULT_MAX_RUNS', '0'))     # 单调度默认重跑上限(0=不限)
#   DRIFT_PROB_THRESHOLD         = float(os.environ.get('DRIFT_PROB_THRESHOLD', '0.15'))      # 概率漂移阈值
#   DRIFT_WEBHOOK_URL            = os.environ.get('DRIFT_WEBHOOK_URL', '').strip() or None    # 漂移告警 webhook


def _cfg_bool(name: str, default: bool) -> bool:
    return bool(getattr(Config, name, default))


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


def _cfg_str(name: str, default: Optional[str]) -> Optional[str]:
    v = getattr(Config, name, default)
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def scheduler_enabled() -> bool:
    return _cfg_bool("SCHEDULER_ENABLED", False)


def tick_seconds() -> int:
    return max(5, _cfg_int("SCHEDULER_TICK_SECONDS", 60))


def max_concurrent() -> int:
    return max(1, _cfg_int("SCHEDULER_MAX_CONCURRENT", 1))


def default_max_runs() -> int:
    return max(0, _cfg_int("SCHEDULER_DEFAULT_MAX_RUNS", 0))


def drift_prob_threshold() -> float:
    t = _cfg_float("DRIFT_PROB_THRESHOLD", 0.15)
    # 阈值取 (0,1]；非法值回退默认，避免「0 阈值=任何抖动都告警」的告警风暴。
    return t if 0.0 < t <= 1.0 else 0.15


def drift_webhook_url() -> Optional[str]:
    return _cfg_str("DRIFT_WEBHOOK_URL", None)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# INFRA-14: the run options a schedule may carry, with the vocabularies POST
# /api/research/run admits (a schedule used to launch whatever it stored).
_VALID_MODES = ("full", "research_only")
_VALID_DEPTHS = ("quick", "standard", "deep")
_VALID_LANGUAGES = ("Chinese", "English", "auto")


def validate_run_options(*, depth: Optional[str], model: Optional[str], language: Optional[str],
                         options: Optional[dict[str, Any]]
                         ) -> tuple[Optional[str], Optional[str], Optional[str], dict[str, Any]]:
    """Normalise a schedule's run options the way the run API does; ValueError when invalid.

    depth: None/'' (Config default) or quick/standard/deep, any case.  model: None/''
    or one of Config.SUPPORTED_DEERFLOW_MODELS, any case.  language: None (Config
    default), '' or 'auto' (the model chooses; stored as ''), Chinese or English.
    options: an object whose optional mode is full/research_only and whose optional
    max_rounds is a strict integer (a bool or 3.5 is refused, as by the API).
    """
    if depth is not None and not isinstance(depth, str):
        raise ValueError(f"depth must be one of {', '.join(_VALID_DEPTHS)}, got {depth!r}")
    depth = (depth or "").strip().lower() or None
    if depth is not None and depth not in _VALID_DEPTHS:
        raise ValueError(f"depth must be one of {', '.join(_VALID_DEPTHS)}, got {depth!r}")
    if model is not None and not isinstance(model, str):
        raise ValueError(f"model must be one of {', '.join(Config.SUPPORTED_DEERFLOW_MODELS)}, got {model!r}")
    model = (model or "").strip().lower() or None
    if model is not None and model not in Config.SUPPORTED_DEERFLOW_MODELS:
        raise ValueError(f"model must be one of {', '.join(Config.SUPPORTED_DEERFLOW_MODELS)}, got {model!r}")
    if language is not None:
        if not isinstance(language, str) or (language.strip() and language.strip() not in _VALID_LANGUAGES):
            raise ValueError(f"language must be one of {', '.join(_VALID_LANGUAGES)}, got {language!r}")
        language = "" if language.strip() in ("", "auto") else language.strip()
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise ValueError(f"options must be an object, got {type(options).__name__}")
    options = dict(options)
    if options.get("mode") is not None and options["mode"] not in _VALID_MODES:
        raise ValueError(f"options.mode must be one of {', '.join(_VALID_MODES)}, got {options['mode']!r}")
    if options.get("max_rounds") is not None:
        options["max_rounds"] = parse_int_option(options["max_rounds"], "options.max_rounds")
    return depth, model, language, options


# ---------------------------------------------------------------------------
# 调度定义持久化（uploads/schedules/<id>/schedule.json）
# ---------------------------------------------------------------------------


class ScheduleStore:
    """读写 uploads/schedules/<id>/schedule.json（原子写 + id 路径防御）。"""

    # uploads/ 根目录复用 Config.UPLOAD_FOLDER（与 pipelines/reports 同级）。
    SCHEDULES_DIR = os.path.join(Config.UPLOAD_FOLDER, "schedules")

    # 调度 id 形如 sched_<hex>；只允许字母数字/下划线/连字符，天然无法 .. 逃逸。
    _ID_RE = re.compile(r"^sched_[A-Za-z0-9_-]+$")

    # 调度记录 schema 版本（形状演进时 +1）。
    SCHEMA_VERSION = 1

    @classmethod
    def _validate_id(cls, schedule_id: str) -> str:
        if (not schedule_id or "/" in schedule_id or "\\" in schedule_id
                or ".." in schedule_id or not cls._ID_RE.match(schedule_id)):
            raise ValueError(f"invalid schedule_id: {schedule_id!r}")
        return schedule_id

    @classmethod
    def _dir(cls, schedule_id: str) -> str:
        cls._validate_id(schedule_id)
        return os.path.join(cls.SCHEDULES_DIR, schedule_id)

    @classmethod
    def _path(cls, schedule_id: str) -> str:
        return os.path.join(cls._dir(schedule_id), "schedule.json")

    @classmethod
    def create(
        cls,
        prompt: str,
        *,
        interval_minutes: int,
        depth: Optional[str] = None,
        options: Optional[dict[str, Any]] = None,
        max_runs: Optional[int] = None,
        project_name: Optional[str] = None,
        language: Optional[str] = None,
        model: Optional[str] = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """新建一条调度定义并落盘，返回该记录。

        interval_minutes 必须 >0。max_runs=None 时取 SCHEDULER_DEFAULT_MAX_RUNS
        （0=不限）。next_run_at 立即置为「现在」，使首次 tick 即触发首跑。
        INFRA-14：depth/model/language/options 按运行 API 的取值域校验并归一化
        （validate_run_options），非法即 ValueError，绝不落盘一条无法启动的调度。
        """
        prompt = (prompt or "").strip()
        if not prompt:
            raise ValueError("prompt 不能为空")
        depth, model, language, options = validate_run_options(
            depth=depth, model=model, language=language, options=options)
        interval_minutes = int(interval_minutes)
        if interval_minutes <= 0:
            raise ValueError("interval_minutes 必须为正整数（分钟）")
        if max_runs is None:
            max_runs = default_max_runs()
        max_runs = max(0, int(max_runs))

        schedule_id = f"sched_{uuid.uuid4().hex[:12]}"
        now = _utcnow()
        record: dict[str, Any] = {
            "schema_version": cls.SCHEMA_VERSION,
            "schedule_id": schedule_id,
            "prompt": prompt,
            "depth": (depth or None),
            "options": dict(options or {}),
            "project_name": project_name or None,
            "research_language": language,   # 三态语义与 PipelineOrchestrator.start 一致
            "research_model": model or None,
            "interval_minutes": interval_minutes,
            "max_runs": max_runs,            # 0 = 不限
            "enabled": bool(enabled),
            "created_at": now,
            "updated_at": now,
            "last_run_at": None,
            "next_run_at": now,              # 首次 tick 即到点
            "run_pipeline_ids": [],          # 历史运行（最新在末尾）
            "drift_history": [],             # 每次重跑相对上一次的漂移摘要
        }
        cls.save(record)
        logger.info("[scheduler] 新建调度 %s（每 %d 分钟）", schedule_id, interval_minutes)
        return record

    @classmethod
    def save(cls, record: dict[str, Any]) -> None:
        schedule_id = cls._validate_id(record["schedule_id"])
        os.makedirs(cls._dir(schedule_id), exist_ok=True)
        record["updated_at"] = _utcnow()
        record.setdefault("schema_version", cls.SCHEMA_VERSION)
        write_json_atomic(cls._path(schedule_id), record, indent=2)

    @classmethod
    def load(cls, schedule_id: str) -> Optional[dict[str, Any]]:
        try:
            path = cls._path(schedule_id)
        except ValueError:
            return None
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    @classmethod
    def delete(cls, schedule_id: str) -> bool:
        import shutil

        try:
            target = cls._dir(schedule_id)
        except ValueError:
            return False
        if not os.path.isdir(target):
            return False
        shutil.rmtree(target, ignore_errors=True)
        return not os.path.isdir(target)

    @classmethod
    def list_schedules(cls) -> list[dict[str, Any]]:
        root = cls.SCHEDULES_DIR
        if not os.path.isdir(root):
            return []
        out: list[dict[str, Any]] = []
        for sid in os.listdir(root):
            rec = cls.load(sid)
            if rec:
                out.append(rec)
        out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return out

    @classmethod
    def set_enabled(cls, schedule_id: str, enabled: bool) -> Optional[dict[str, Any]]:
        rec = cls.load(schedule_id)
        if not rec:
            return None
        rec["enabled"] = bool(enabled)
        cls.save(rec)
        return rec


# ---------------------------------------------------------------------------
# 漂移检测：比较两份 forecast.json → 漂移报告
# ---------------------------------------------------------------------------


def _forecast_path_for_pipeline(pipeline_id: str) -> Optional[str]:
    """定位某条管线产出的结构化预测 forecast.json（报告文件夹下）。"""
    data = PipelineManager.load(pipeline_id)
    if not data:
        return None
    report_id = data.get("report_id")
    if not report_id:
        return None
    path = os.path.join(ReportManager._get_report_folder(report_id), "forecast.json")
    return path if os.path.exists(path) else None


def _load_json(path: Optional[str]) -> Optional[dict[str, Any]]:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _actor_names(actors: Optional[dict[str, Any]], limit: int = 12) -> list[str]:
    """从 actors.json 取 top 角色名（按出现顺序，研究档案已大致按重要性排）。"""
    if not isinstance(actors, dict):
        return []
    rows = actors.get("actors") or []
    out: list[str] = []
    for a in rows:
        if isinstance(a, dict) and a.get("name"):
            out.append(str(a["name"]).strip())
        if len(out) >= limit:
            break
    return out


def _coalition_labels(communities: Any, limit: int = 12) -> list[str]:
    """从 communities.json 取 top 联盟/社区标签（容忍多种形状）。"""
    items: list[Any] = []
    if isinstance(communities, list):
        items = communities
    elif isinstance(communities, dict):
        items = communities.get("communities") or list(communities.values())
    out: list[str] = []
    for c in items:
        label: Optional[str] = None
        if isinstance(c, dict):
            label = c.get("name") or c.get("label") or c.get("summary") or c.get("id")
        elif isinstance(c, str):
            label = c
        if label:
            out.append(str(label).strip())
        if len(out) >= limit:
            break
    return out


def forecast_diff(
    prev: Optional[dict[str, Any]],
    curr: Optional[dict[str, Any]],
    *,
    threshold: Optional[float] = None,
    prev_actors: Optional[dict[str, Any]] = None,
    curr_actors: Optional[dict[str, Any]] = None,
    prev_coalitions: Any = None,
    curr_coalitions: Any = None,
) -> dict[str, Any]:
    """比较两份结构化预测（+可选的角色/联盟集合）→ 漂移报告。

    按归一化情景名匹配（口径与 ensemble.aggregate_forecasts 一致）；对每个匹配上的
    情景计算 ``delta=|curr.p - prev.p|``，超过 threshold 即标记漂移。新出现/消失的
    情景一律视为漂移。另对 top 角色/联盟做集合差。纯函数、无副作用、可离线单测。

    返回 ``drift`` 布尔 + 逐项明细 + 一段人类可读 ``summary``。
    """
    if threshold is None:
        threshold = drift_prob_threshold()

    def _scen_map(fc: Optional[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        m: dict[str, dict[str, Any]] = {}
        if isinstance(fc, dict):
            for s in fc.get("scenarios") or []:
                if not isinstance(s, dict):
                    continue
                key = _norm_name(s.get("name"))
                if not key:
                    continue
                try:
                    p = float(s.get("probability") or 0.0)
                except (TypeError, ValueError):
                    p = 0.0
                m[key] = {"name": s.get("name"), "probability": p}
        return m

    prev_m = _scen_map(prev)
    curr_m = _scen_map(curr)

    scenario_changes: list[dict[str, Any]] = []
    new_scenarios: list[str] = []
    dropped_scenarios: list[str] = []
    max_delta = 0.0

    for key, cur in curr_m.items():
        if key in prev_m:
            delta = round(cur["probability"] - prev_m[key]["probability"], 4)
            adelta = abs(delta)
            max_delta = max(max_delta, adelta)
            if adelta >= threshold:
                scenario_changes.append({
                    "name": cur["name"],
                    "prev_probability": round(prev_m[key]["probability"], 4),
                    "curr_probability": round(cur["probability"], 4),
                    "delta": delta,
                })
        else:
            new_scenarios.append(str(cur["name"]))
            max_delta = max(max_delta, cur["probability"])
    for key, pv in prev_m.items():
        if key not in curr_m:
            dropped_scenarios.append(str(pv["name"]))
            max_delta = max(max_delta, pv["probability"])

    # 角色 / 联盟集合差（best-effort；缺省即空）
    prev_actor_names = _actor_names(prev_actors)
    curr_actor_names = _actor_names(curr_actors)
    new_actors = [a for a in curr_actor_names if a not in set(prev_actor_names)]
    gone_actors = [a for a in prev_actor_names if a not in set(curr_actor_names)]

    prev_coal = _coalition_labels(prev_coalitions)
    curr_coal = _coalition_labels(curr_coalitions)
    new_coalitions = [c for c in curr_coal if c not in set(prev_coal)]

    drift = bool(
        scenario_changes or new_scenarios or dropped_scenarios
        or new_actors or new_coalitions
    )

    # 一句话摘要（用于日志 / webhook / UI 高亮）
    parts: list[str] = []
    if scenario_changes:
        top = max(scenario_changes, key=lambda c: abs(c["delta"]))
        parts.append(
            f"情景「{top['name']}」概率 {top['prev_probability']:.0%}→{top['curr_probability']:.0%}"
            f"（Δ{top['delta']:+.0%}）"
        )
    if new_scenarios:
        parts.append("新增情景：" + "、".join(new_scenarios[:3]))
    if dropped_scenarios:
        parts.append("消失情景：" + "、".join(dropped_scenarios[:3]))
    if new_actors:
        parts.append("新主导角色：" + "、".join(new_actors[:3]))
    if new_coalitions:
        parts.append("新联盟：" + "、".join(new_coalitions[:3]))
    summary = "；".join(parts) if parts else "无实质性漂移"

    return {
        "drift": drift,
        "threshold": round(float(threshold), 4),
        "max_prob_delta": round(max_delta, 4),
        "scenario_changes": scenario_changes,
        "new_scenarios": new_scenarios,
        "dropped_scenarios": dropped_scenarios,
        "new_actors": new_actors,
        "gone_actors": gone_actors,
        "new_coalitions": new_coalitions,
        "summary": summary,
        "schema_version": 1,
    }


def diff_pipelines(prev_pipeline_id: str, curr_pipeline_id: str) -> dict[str, Any]:
    """对两条已完成管线的预测+档案做漂移比较（CLI / 守护进程共用）。"""
    prev_fc = _load_json(_forecast_path_for_pipeline(prev_pipeline_id))
    curr_fc = _load_json(_forecast_path_for_pipeline(curr_pipeline_id))

    def _artifacts(pipeline_id: str) -> tuple[Optional[dict], Any]:
        data = PipelineManager.load(pipeline_id) or {}
        arts = data.get("artifacts") or {}
        actors = _load_json(arts.get("dossier"))
        coalitions = _load_json(arts.get("communities"))
        # communities.json 顶层可能是 list（_load_json 只接 dict）→ 再单独读一次容错。
        if coalitions is None and arts.get("communities") and os.path.exists(arts["communities"]):
            try:
                with open(arts["communities"], "r", encoding="utf-8") as f:
                    coalitions = json.load(f)
            except Exception:
                coalitions = None
        return actors, coalitions

    prev_actors, prev_coal = _artifacts(prev_pipeline_id)
    curr_actors, curr_coal = _artifacts(curr_pipeline_id)

    report = forecast_diff(
        prev_fc, curr_fc,
        prev_actors=prev_actors, curr_actors=curr_actors,
        prev_coalitions=prev_coal, curr_coalitions=curr_coal,
    )
    report["prev_pipeline_id"] = prev_pipeline_id
    report["curr_pipeline_id"] = curr_pipeline_id
    report["has_prev_forecast"] = prev_fc is not None
    report["has_curr_forecast"] = curr_fc is not None
    return report


# ---------------------------------------------------------------------------
# webhook 漂移告警（可选；经 validate_safe_url 防 SSRF）
# ---------------------------------------------------------------------------


def fire_drift_webhook(url: str, payload: dict[str, Any], *, timeout: float = 10.0) -> bool:
    """向 url POST 一段漂移摘要 JSON。失败仅告警、返回 False（绝不影响调度）。"""
    try:
        from app.utils.security import validate_safe_url
        # 暴露到环回之外时，遵循同一私网阻断策略（与 apply_provider 一致）。
        validate_safe_url(url, block_private=_cfg_bool("APP_BLOCK_PRIVATE_URLS", False))
    except Exception as e:  # noqa: BLE001
        logger.warning("[scheduler] 漂移 webhook URL 非法，跳过：%s", e)
        return False
    try:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        req = _urlrequest.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with _urlrequest.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — URL 已经 validate_safe_url 校验
            code = getattr(resp, "status", None) or resp.getcode()
            ok = 200 <= int(code) < 300
            if not ok:
                logger.warning("[scheduler] 漂移 webhook 返回非 2xx：%s", code)
            return ok
    except (_urlerror.URLError, OSError, ValueError) as e:
        logger.warning("[scheduler] 漂移 webhook 发送失败：%s", e)
        return False


# ---------------------------------------------------------------------------
# 守护进程：due-check 循环
# ---------------------------------------------------------------------------


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


class Scheduler:
    """定时重跑守护线程（与 SimulationRunner 的 monitor 线程同构）。

    全局单例（_thread）。``maybe_start`` 仅在 SCHEDULER_ENABLED=true 时起线程，
    故默认对现有进程零影响（可在 backend/app/__init__.py 调用——见文末 skipped 说明）。
    """

    _thread: Optional[threading.Thread] = None
    _stop_event: threading.Event = threading.Event()
    _lock: threading.Lock = threading.Lock()

    # ---- 生命周期 ----

    @classmethod
    def maybe_start(cls) -> bool:
        """若 SCHEDULER_ENABLED=true 且尚未启动，则起守护线程。返回是否已在运行。"""
        if not scheduler_enabled():
            return False
        with cls._lock:
            if cls._thread is not None and cls._thread.is_alive():
                return True
            cls._stop_event.clear()
            t = threading.Thread(target=cls._loop, name="scheduler", daemon=True)
            cls._thread = t
            t.start()
            logger.info(
                "[scheduler] 守护线程已启动（tick=%ds，全局并发上限=%d）",
                tick_seconds(), max_concurrent(),
            )
            return True

    @classmethod
    def stop(cls) -> None:
        cls._stop_event.set()

    @classmethod
    def _loop(cls) -> None:
        # 启动即先对孤儿管线做一次回收（与后端 reconcile_orphans 配合：被本进程标 running
        # 的孤儿在这里被纠正，避免 due-check 把它误判成「仍在飞」而永久跳过）。
        try:
            PipelineOrchestrator.reconcile_orphans()
        except Exception:  # noqa: BLE001 — 回收失败不应阻止调度循环
            logger.warning("[scheduler] 启动期孤儿回收失败（忽略）", exc_info=True)
        while not cls._stop_event.is_set():
            try:
                cls.tick()
            except Exception:  # noqa: BLE001 — 单次 tick 异常绝不能杀掉守护线程
                logger.error("[scheduler] tick 异常（忽略，继续）", exc_info=True)
            # 用 Event.wait 而非 sleep，支持 stop() 即时唤醒。
            cls._stop_event.wait(timeout=tick_seconds())

    # ---- due-check ----

    @classmethod
    def _running_pipeline_count(cls) -> int:
        """当前持久化为 running 的管线数（全局并发上限的判据）。"""
        try:
            return sum(1 for p in PipelineManager.list_pipelines() if p.get("status") == "running")
        except Exception:  # noqa: BLE001
            return 0

    @classmethod
    def _schedule_has_inflight(cls, record: dict[str, Any]) -> bool:
        """该调度的最近一次运行是否仍在飞（幂等 due-check：避免重复触发）。"""
        ids = record.get("run_pipeline_ids") or []
        if not ids:
            return False
        data = PipelineManager.load(ids[-1])
        return bool(data and data.get("status") == "running")

    @classmethod
    def tick(cls, *, now: Optional[datetime] = None, force_ids: Optional[set[str]] = None) -> list[str]:
        """扫描所有调度，对到点 + enabled + 未达上限者触发一次重跑。

        Args:
            now: 注入「当前时间」便于测试；默认 UTC now。
            force_ids: 这些 schedule_id 无视 next_run_at 强制触发（CLI run-once 用）。

        Returns:
            本次触发的 (schedule_id) 列表。
        """
        now = now or datetime.now(timezone.utc)
        force_ids = force_ids or set()
        triggered: list[str] = []

        running = cls._running_pipeline_count()
        cap = max_concurrent()

        for record in ScheduleStore.list_schedules():
            sid = record.get("schedule_id")
            if not sid:
                continue
            forced = sid in force_ids
            if not forced and not record.get("enabled", False):
                continue

            # 到点判定
            next_at = _parse_iso(record.get("next_run_at"))
            due = forced or (next_at is None) or (now >= next_at)
            if not due:
                continue

            # 上限判定（max_runs=0 不限）
            max_runs = int(record.get("max_runs") or 0)
            done = len(record.get("run_pipeline_ids") or [])
            if max_runs and done >= max_runs:
                if record.get("enabled"):
                    record["enabled"] = False  # 达上限自动停用，避免每 tick 重复评估
                    ScheduleStore.save(record)
                    logger.info("[scheduler] 调度 %s 已达运行上限 %d，自动停用", sid, max_runs)
                continue

            # 幂等：该调度上一次运行仍在飞 → 跳过（不堆叠）。
            if cls._schedule_has_inflight(record):
                logger.info("[scheduler] 调度 %s 上一次运行仍在飞，本 tick 跳过", sid)
                continue

            # 全局并发上限
            if running >= cap:
                logger.info(
                    "[scheduler] 达全局并发上限（%d），调度 %s 推迟到下一 tick", cap, sid
                )
                # 不更新 next_run_at：下一 tick 仍视为到点，尽快补跑。
                continue

            pipeline_id = cls._launch(record, now)
            if pipeline_id:
                running += 1
                triggered.append(sid)
        return triggered

    @classmethod
    def _launch(cls, record: dict[str, Any], now: datetime) -> Optional[str]:
        """对一条调度起一次管线，更新 last/next_run_at + run 列表 + 漂移摘要。"""
        sid = record["schedule_id"]
        interval = int(record.get("interval_minutes") or 60)
        # INFRA-14: re-validate the stored options (a record written before validation
        # existed, or edited by hand); an invalid schedule is skipped, never launched.
        try:
            depth, model, language, opts = validate_run_options(
                depth=record.get("depth"), model=record.get("research_model"),
                language=record.get("research_language"), options=record.get("options"))
        except ValueError as e:
            logger.error("[scheduler] 调度 %s 的运行参数非法，跳过：%s", sid, e)
            record["last_error"] = f"invalid schedule: {e}"
            record["next_run_at"] = (now + timedelta(minutes=interval)).isoformat()
            ScheduleStore.save(record)
            return None
        try:
            state = PipelineOrchestrator.start(
                record["prompt"],
                mode=str(opts.get("mode") or "full"),
                project_name=record.get("project_name"),
                depth=depth,
                max_rounds=opts.get("max_rounds"),
                language=language,
                model=model,
            )
        except Exception as e:  # noqa: BLE001 — 起管线失败不应杀循环；记录并推迟到下次。
            logger.error("[scheduler] 调度 %s 起管线失败：%s", sid, e, exc_info=True)
            record["last_error"] = f"launch failed: {e}"
            record["next_run_at"] = (now + timedelta(minutes=interval)).isoformat()
            record["updated_at"] = _utcnow()
            ScheduleStore.save(record)
            return None

        new_pid = state.pipeline_id
        prev_pid = (record.get("run_pipeline_ids") or [None])[-1]

        record["last_run_at"] = now.isoformat()
        record.pop("last_error", None)
        record["next_run_at"] = (now + timedelta(minutes=interval)).isoformat()
        record.setdefault("run_pipeline_ids", []).append(new_pid)
        ScheduleStore.save(record)
        logger.info(
            "[scheduler] 调度 %s 触发重跑 → %s（上一次 %s）", sid, new_pid, prev_pid or "无"
        )

        # 漂移检测 + webhook 在后台等待本次管线完成（不阻塞 due-check 循环）。
        # 仅当存在「上一次运行」时才有可比对象。
        if prev_pid:
            t = threading.Thread(
                target=cls._await_and_diff,
                args=(sid, prev_pid, new_pid),
                name=f"scheduler-diff-{sid}",
                daemon=True,
            )
            t.start()
        return new_pid

    @classmethod
    def _await_and_diff(cls, schedule_id: str, prev_pid: str, curr_pid: str) -> None:
        """等待新管线产出 forecast.json，比对上一次，落漂移摘要并按需 webhook。"""
        # 等待新管线到达终态（completed/failed/cancelled）；最长等待按研究深度兜底。
        deadline = time.time() + max(
            600, _cfg_int("DEERFLOW_RESEARCH_TIMEOUT", 10800) + 1800
        )
        while time.time() < deadline and not cls._stop_event.is_set():
            data = PipelineManager.load(curr_pid)
            status = (data or {}).get("status")
            if status in ("completed", "failed", "cancelled"):
                break
            cls._stop_event.wait(timeout=30)

        try:
            report = diff_pipelines(prev_pid, curr_pid)
        except Exception:  # noqa: BLE001
            logger.warning("[scheduler] 调度 %s 漂移比对失败（忽略）", schedule_id, exc_info=True)
            return

        # 把漂移摘要追加进调度记录（供 UI 时间线高亮）。
        rec = ScheduleStore.load(schedule_id)
        if rec is not None:
            entry = {
                "at": _utcnow(),
                "prev_pipeline_id": prev_pid,
                "curr_pipeline_id": curr_pid,
                "drift": report.get("drift"),
                "max_prob_delta": report.get("max_prob_delta"),
                "summary": report.get("summary"),
            }
            rec.setdefault("drift_history", []).append(entry)
            ScheduleStore.save(rec)

        if report.get("drift"):
            logger.info("[scheduler] 调度 %s 检测到漂移：%s", schedule_id, report.get("summary"))
            url = drift_webhook_url()
            if url:
                fire_drift_webhook(url, {
                    "event": "forecast_drift",
                    "schedule_id": schedule_id,
                    "prev_pipeline_id": prev_pid,
                    "curr_pipeline_id": curr_pid,
                    "report": report,
                })
        else:
            logger.info("[scheduler] 调度 %s 重跑无实质性漂移", schedule_id)


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scheduled_rerun.py",
        description="定时重跑已保存的预测定义并检测漂移（I-9-6；默认全关，需 SCHEDULER_ENABLED=true 才起守护线程）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("add", help="新建一条调度")
    sp.add_argument("--prompt", required=True, help="预测问题（与 POST /run 同义）")
    sp.add_argument("--interval-minutes", type=int, required=True, help="重跑间隔（分钟，>0）")
    sp.add_argument("--depth", default=None, help="研究深度 quick/standard/deep（默认用 Config）")
    sp.add_argument("--max-runs", type=int, default=None, help="重跑次数上限（0=不限，默认取 SCHEDULER_DEFAULT_MAX_RUNS）")
    sp.add_argument("--project-name", default=None, help="项目名（可选）")
    sp.add_argument("--language", default=None, help="研究语言覆盖（可选）")
    sp.add_argument("--model", default=None, help="研究模型覆盖（可选）")
    sp.add_argument("--max-rounds", type=int, default=None, help="模拟轮数上限（可选）")
    sp.add_argument("--disabled", action="store_true", help="新建后处于停用状态")

    sub.add_parser("list", help="列出所有调度")

    sp = sub.add_parser("show", help="查看一条调度详情")
    sp.add_argument("schedule_id")

    sp = sub.add_parser("enable", help="启用一条调度")
    sp.add_argument("schedule_id")

    sp = sub.add_parser("disable", help="停用一条调度")
    sp.add_argument("schedule_id")

    sp = sub.add_parser("delete", help="删除一条调度")
    sp.add_argument("schedule_id")

    sp = sub.add_parser("run-once", help="立即触发一条调度（无视 next_run_at）")
    sp.add_argument("schedule_id")

    sub.add_parser("tick", help="跑一遍 due-check 后退出（适合外部 cron 驱动）")

    sub.add_parser("daemon", help="常驻守护线程（需 SCHEDULER_ENABLED=true）")

    sp = sub.add_parser("diff", help="打印两条管线预测之间的漂移报告")
    sp.add_argument("prev_pipeline_id")
    sp.add_argument("curr_pipeline_id")

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    cmd = args.cmd

    if cmd == "add":
        try:
            rec = ScheduleStore.create(
                args.prompt,
                interval_minutes=args.interval_minutes,
                depth=args.depth,
                options={"max_rounds": args.max_rounds} if args.max_rounds is not None else {},
                max_runs=args.max_runs,
                project_name=args.project_name,
                language=args.language,
                model=args.model,
                enabled=not args.disabled,
            )
        except ValueError as e:
            print(f"调度参数非法: {e}", file=sys.stderr)
            return 2
        _print_json(rec)
        return 0

    if cmd == "list":
        _print_json([
            {
                "schedule_id": r.get("schedule_id"),
                "enabled": r.get("enabled"),
                "interval_minutes": r.get("interval_minutes"),
                "runs": len(r.get("run_pipeline_ids") or []),
                "max_runs": r.get("max_runs"),
                "next_run_at": r.get("next_run_at"),
                "last_run_at": r.get("last_run_at"),
                "prompt": (r.get("prompt") or "")[:80],
            }
            for r in ScheduleStore.list_schedules()
        ])
        return 0

    if cmd == "show":
        rec = ScheduleStore.load(args.schedule_id)
        if rec is None:
            print(f"未找到调度: {args.schedule_id}", file=sys.stderr)
            return 1
        _print_json(rec)
        return 0

    if cmd in ("enable", "disable"):
        rec = ScheduleStore.set_enabled(args.schedule_id, cmd == "enable")
        if rec is None:
            print(f"未找到调度: {args.schedule_id}", file=sys.stderr)
            return 1
        print(f"{args.schedule_id} -> enabled={rec['enabled']}")
        return 0

    if cmd == "delete":
        ok = ScheduleStore.delete(args.schedule_id)
        print(f"{args.schedule_id} -> {'deleted' if ok else 'not_found'}")
        return 0 if ok else 1

    if cmd == "run-once":
        rec = ScheduleStore.load(args.schedule_id)
        if rec is None:
            print(f"未找到调度: {args.schedule_id}", file=sys.stderr)
            return 1
        triggered = Scheduler.tick(force_ids={args.schedule_id})
        if args.schedule_id in triggered:
            rec2 = ScheduleStore.load(args.schedule_id) or {}
            print(f"已触发 {args.schedule_id} -> {(rec2.get('run_pipeline_ids') or ['?'])[-1]}")
            return 0
        print(f"未触发 {args.schedule_id}（可能达并发上限/上一次仍在飞）", file=sys.stderr)
        return 1

    if cmd == "tick":
        triggered = Scheduler.tick()
        print(f"本次触发 {len(triggered)} 条调度: {triggered}")
        return 0

    if cmd == "daemon":
        if not scheduler_enabled():
            print(
                "SCHEDULER_ENABLED 未开启（默认关）。在 .env 设 SCHEDULER_ENABLED=true 后重试。",
                file=sys.stderr,
            )
            return 2
        Scheduler.maybe_start()
        print("调度守护线程已启动；Ctrl-C 退出。")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            Scheduler.stop()
            print("\n已停止。")
        return 0

    if cmd == "diff":
        report = diff_pipelines(args.prev_pipeline_id, args.curr_pipeline_id)
        _print_json(report)
        return 0

    return 2  # 不可达（subparser required）


if __name__ == "__main__":
    raise SystemExit(main())
