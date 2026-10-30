"""i8 回归：MON-1 判定监测的进程内调度（LOOP-017「resolution monitor never ran」）。

钉住：源码默认每日 24 小时；显式 0 保留关闭行为；开启后周期触发走
trigger_once 的在飞去重；手动端点 202/409 语义；子进程命令形状与超时降级。
全离线：subprocess 一律 monkeypatch，零网络。
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time

from flask import Flask

from app.api import research_bp
from app.config import Config
import app.services.resolution_autorun as ra


def _drain_inflight(timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while ra.is_inflight() and time.time() < deadline:
        time.sleep(0.01)
    assert not ra.is_inflight(), "in-flight 标志未在期限内复位"


def test_source_default_is_daily_and_explicit_disable_is_inert(monkeypatch):
    """Approved daily source default replaces off; an existing env=0 still disables."""
    from pathlib import Path
    source = (Path(__file__).parents[1] / "app/config.py").read_text()
    assert "RESOLUTION_MONITOR_AUTORUN_HOURS', '24'" in source
    monkeypatch.setattr(Config, "RESOLUTION_MONITOR_AUTORUN_HOURS", 0)
    assert ra.start() is None
    assert ra.start(0) is None
    assert ra.start(-1) is None


def test_run_once_invokes_script_with_all_recent(monkeypatch):
    calls = {}

    def _fake_run(cmd, **kw):
        calls["cmd"] = cmd
        calls["kw"] = kw

        class _P:
            returncode = 0
            stdout = "{}"
            stderr = ""
        return _P()

    monkeypatch.setattr(subprocess, "run", _fake_run)
    out = ra._run_once()
    assert out["ok"] is True
    assert calls["cmd"][0] == sys.executable
    assert calls["cmd"][1].endswith("scripts/resolution_monitor.py")
    assert calls["cmd"][2:] == ["run", "--all-recent"]
    assert calls["kw"]["timeout"] == ra._RUN_TIMEOUT_SECONDS


def test_run_once_timeout_degrades(monkeypatch):
    def _boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)

    monkeypatch.setattr(subprocess, "run", _boom)
    out = ra._run_once()
    assert out == {"ok": False, "error": "timeout"}


def test_trigger_once_dedupes_inflight(monkeypatch):
    release = threading.Event()

    def _slow_run():
        release.wait(2.0)
        return {"ok": True}

    monkeypatch.setattr(ra, "_run_once", _slow_run)
    assert ra.trigger_once() is True
    try:
        assert ra.is_inflight() is True
        assert ra.trigger_once() is False  # 在飞去重
    finally:
        release.set()
    _drain_inflight()
    # 复位后可再次触发
    monkeypatch.setattr(ra, "_run_once", lambda: {"ok": True})
    assert ra.trigger_once() is True
    _drain_inflight()


def test_start_scheduler_fires_trigger_periodically(monkeypatch):
    fired = threading.Event()
    count = {"n": 0}

    def _rec():
        count["n"] += 1
        fired.set()
        return True

    monkeypatch.setattr(ra, "trigger_once", _rec)
    t = ra.start(interval_hours=0.0001, initial_delay_s=0.01)  # ~0.36s 周期
    assert t is not None and t.is_alive()
    try:
        assert fired.wait(2.0), "调度线程未在期限内触发首轮"
        assert count["n"] >= 1
    finally:
        t._drf_stop_event.set()  # noqa: SLF001 — 测试关停钩子
        t.join(timeout=2.0)
    assert not t.is_alive()


def test_manual_endpoint_202_then_409(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(research_bp, url_prefix="/api/research")
    client = app.test_client()

    monkeypatch.setattr(ra, "trigger_once", lambda: True)
    resp = client.post("/api/research/resolution-monitor/run")
    assert resp.status_code == 202
    assert resp.get_json()["data"]["started"] is True

    monkeypatch.setattr(ra, "trigger_once", lambda: False)
    resp2 = client.post("/api/research/resolution-monitor/run")
    assert resp2.status_code == 409
    assert resp2.get_json()["inflight"] is True
