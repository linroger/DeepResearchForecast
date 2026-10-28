"""MON-1 判定监测的进程内调度（i8，LOOP-017 尾巴「resolution monitor never ran」）。

`scripts/resolution_monitor.py` 是纯旁路脚本：对已发布报告的锚定市场重报价、查询判定
终态、落 price_track/resolutions/monitor_report。它设计成 cron 驱动，但从未有人装过
cron——判定账本因此永远空着，Brier 自评没有样本。本模块给它一个最小的进程内调度器：

* `RESOLUTION_MONITOR_AUTORUN_HOURS > 0` 时，后台 daemon 线程每 N 小时以**子进程**跑一次
  `run --all-recent`（子进程隔离脚本崩溃/网络挂起；15 分钟硬超时）。源码期望周期 24h；
  部署 .env 的 0 仍关闭调度。仅由 run.py 生产入口调用 start()，导入不会启动。
* `trigger_once()` 供 API 手动触发一次（后台线程 + 在飞去重），UI/curl 均可用。

脚本本身只打 keyless 公共 Gamma 端点，无 LLM/付费调用；调度器不改其任何语义。
"""

from __future__ import annotations

import os
import math
import subprocess
import sys
import threading
from typing import Optional

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('mirofish.resolution_autorun')

_RUN_TIMEOUT_SECONDS = 15 * 60
_inflight_lock = threading.Lock()
_inflight = False


def _script_path() -> str:
    backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(backend_root, "scripts", "resolution_monitor.py")


def _run_once() -> dict:
    """跑一次 `run --all-recent`（阻塞当前线程；调用方负责放到后台）。"""
    script = _script_path()
    if not os.path.isfile(script):
        return {"ok": False, "error": f"resolution_monitor.py not found: {script}"}
    cmd = [sys.executable, script, "run", "--all-recent"]
    try:
        proc = subprocess.run(  # noqa: S603 — 自家脚本、无用户输入拼接
            cmd, capture_output=True, text=True, timeout=_RUN_TIMEOUT_SECONDS,
            cwd=os.path.dirname(script),
        )
    except subprocess.TimeoutExpired:
        logger.error(f"resolution monitor 超时（>{_RUN_TIMEOUT_SECONDS}s）被杀")
        return {"ok": False, "error": "timeout"}
    except OSError as exc:
        logger.error(f"resolution monitor 启动失败: {exc}")
        return {"ok": False, "error": str(exc)}
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-500:]
        logger.warning(f"resolution monitor 退出码 {proc.returncode}: {tail}")
        return {"ok": False, "returncode": proc.returncode, "tail": tail}
    logger.info("resolution monitor 一轮完成")
    return {"ok": True, "returncode": 0}


def trigger_once() -> bool:
    """后台跑一次（在飞去重）。返回是否真正启动了新的一轮。"""
    global _inflight
    with _inflight_lock:
        if _inflight:
            return False
        _inflight = True

    def _worker() -> None:
        global _inflight
        try:
            _run_once()
        finally:
            with _inflight_lock:
                _inflight = False

    threading.Thread(target=_worker, name="resolution-monitor-once", daemon=True).start()
    return True


def is_inflight() -> bool:
    with _inflight_lock:
        return _inflight


def run_schedule(interval_hours, *, wait, trigger, initial_delay_s=60.0):
    """Run the cadence using injectable clock waiting; imports never start it.

    ``wait(seconds)`` returns true on cancellation, like Event.wait. A fake wait
    advances time synchronously in tests; the production loop uses its stop event.
    """
    hours = float(interval_hours)
    delay = float(initial_delay_s)
    if not math.isfinite(hours) or hours <= 0 or not math.isfinite(delay) or delay < 0:
        return
    if wait(delay):
        return
    while True:
        trigger()
        if wait(hours * 3600.0):
            return


def start(interval_hours: Optional[float] = None, *,
          initial_delay_s: float = 60.0) -> Optional[threading.Thread]:
    """按 Config 周期启动调度线程；<=0 → None（不启动，今日行为）。

    首轮延迟 initial_delay_s（生产 60s，让后端先完成启动；测试可缩短），随后每 interval
    小时一轮；每轮走 trigger_once 的在飞去重（手动触发与周期触发绝不并发双跑）。"""
    hours = interval_hours
    if hours is None:
        try:
            hours = float(getattr(Config, "RESOLUTION_MONITOR_AUTORUN_HOURS", 0) or 0)
        except (TypeError, ValueError):
            hours = 0.0
    try:
        hours = float(hours)
        delay = float(initial_delay_s)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(hours) or hours <= 0 or not math.isfinite(delay) or delay < 0:
        return None
    stop = threading.Event()

    def _loop() -> None:
        run_schedule(hours, wait=stop.wait, trigger=trigger_once, initial_delay_s=delay)

    t = threading.Thread(target=_loop, name="resolution-monitor-autorun", daemon=True)
    t._drf_stop_event = stop  # type: ignore[attr-defined] — 测试/关停可置位
    t.start()
    logger.info(f"resolution monitor 自动调度已启动（每 {hours}h 一轮，首轮延迟 {delay}s）")
    return t
