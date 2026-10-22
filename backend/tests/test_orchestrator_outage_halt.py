"""DEFECT-1：run 级提供方中断熔断（LLM_OUTAGE_HALT_CONSECUTIVE）的离线红测。

复盘背景：2026-07-08 提供方额度耗尽后，一条管线以最高 231 错误/分钟连续锤了 ~26 小时
（10,584 行 ERROR）；07-15 报告阶段只做「单报告提前中止」（30 次）然后继续下一个报告，
从未有任何运行级止损。覆盖：

- 旋钮读取（env 显式非零优先 → Config 属性 → 内建默认 10；≤0 关闭）；
- 分类器只认提供方级失败（配额/认证/连接/双通道熔断冷却）——内容审查(422)、JSON
  解析错误、预算护栏、取消信号既不计数也不清零；
- 熔断器：连续 N 次提供方级失败（零成功间隔）→ tripped；任一成功清零；
- LLMClient.chat 探针：失败计数、成功清零、tripped 后快速失败（不再发起真实调用）；
- 进度回调（_make_stage_updater.update）在 tripped 后抬升 ProviderOutageHalt；
- _halt_for_provider_outage 落成 status='failed' 的**既有**可恢复检查点态（resume()
  接受 failed/cancelled）；
- 子进程阶段边界计数（_note_provider_stage_failure）；
- 旋钮关闭 → 不注册熔断器、探针完全透传（legacy 行为逐字节不变）。

全部离线：零网络、零真实 LLM。
"""

import pytest

from app.config import Config
from app.services import pipeline_orchestrator as po
from app.utils import telemetry as tel
from app.utils.llm_client import LLMClient


@pytest.fixture
def clean_outage_state():
    """探针/熔断器注册表是进程级的——测试前后都还原，避免跨测试泄漏。"""
    po._uninstall_llm_outage_probe()
    with po._RUN_OUTAGE_LOCK:
        po._RUN_OUTAGE_BREAKERS.clear()
    yield
    po._uninstall_llm_outage_probe()
    with po._RUN_OUTAGE_LOCK:
        po._RUN_OUTAGE_BREAKERS.clear()


# ------------------------------------------------------------------ 旋钮读取
def test_outage_threshold_env_config_fallback(monkeypatch):
    monkeypatch.delenv("LLM_OUTAGE_HALT_CONSECUTIVE", raising=False)
    monkeypatch.delattr(Config, "LLM_OUTAGE_HALT_CONSECUTIVE", raising=False)
    assert po._outage_halt_threshold() == 10          # 内建默认
    monkeypatch.setattr(Config, "LLM_OUTAGE_HALT_CONSECUTIVE", 7, raising=False)
    assert po._outage_halt_threshold() == 7           # Config 属性
    monkeypatch.setenv("LLM_OUTAGE_HALT_CONSECUTIVE", "3")
    assert po._outage_halt_threshold() == 3           # env 显式非零优先
    monkeypatch.setenv("LLM_OUTAGE_HALT_CONSECUTIVE", "-1")
    assert po._outage_halt_threshold() == -1          # env 负数显式关闭
    monkeypatch.setenv("LLM_OUTAGE_HALT_CONSECUTIVE", "0")
    assert po._outage_halt_threshold() == 7           # env '0' 按折叠语义落回 Config
    monkeypatch.setattr(Config, "LLM_OUTAGE_HALT_CONSECUTIVE", 0, raising=False)
    assert po._outage_halt_threshold() == 0           # Config 0 → 关闭
    monkeypatch.setenv("LLM_OUTAGE_HALT_CONSECUTIVE", "garbage")
    assert po._outage_halt_threshold() == 0           # 垃圾 env → 回退 Config


# ------------------------------------------------------------------ 分类器
@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (RuntimeError("429 rate limit exceeded"), "quota"),
        (RuntimeError("provider quota exhausted, usage limit reached"), "quota"),
        (RuntimeError(
            "LLM 调用失败：主提供方 minimax 处于 422/429 熔断冷却，且回退提供方不可用"),
         "circuit_breaker"),
        (RuntimeError("circuit-breaker: minimax in 422/429 cooldown"),
         "circuit_breaker"),
        (RuntimeError("AuthenticationError: invalid authentication credentials"),
         "auth"),
        (RuntimeError("APIConnectionError: Connection refused"), "connection"),
        (ConnectionError("boom"), "connection"),
        (TimeoutError("read deadline"), "connection"),
        (RuntimeError("Claude CLI timed out after 300s"), "connection"),
        # —— 非提供方级：不计数 ——
        (RuntimeError("422 new_sensitive content filter"), None),
        (ValueError("LLM返回的JSON格式无效: {"), None),
        (RuntimeError(""), None),
        (po.PipelineCancelled("用户取消"), None),
        (po.ProviderOutageHalt("已止损"), None),
        (RuntimeError(f"{po._PROVIDER_OUTAGE_FAST_FAIL_PREFIX}: 快速失败"), None),
    ],
)
def test_classify_provider_outage_matrix(exc, expected):
    assert po._classify_provider_outage(exc) == expected


def test_budget_exceeded_is_not_provider_outage():
    from app.utils.telemetry import BudgetExceeded
    assert po._classify_provider_outage(
        BudgetExceeded("run exceeded token budget: 999 > 1")) is None


# ------------------------------------------------------------------ 熔断器语义
def test_breaker_trips_after_n_consecutive_and_resets_on_success():
    br = po._RunOutageBreaker("pipe_outageunit", 3)
    quota = RuntimeError("429 quota exhausted")

    assert br.note_failure(quota) is False
    assert br.consecutive == 1
    # 非提供方级失败：既不计数也不清零
    assert br.note_failure(ValueError("LLM返回的JSON格式无效")) is False
    assert br.consecutive == 1
    # 任一成功清零
    br.record_success()
    assert br.consecutive == 0 and br.tripped is False
    # 连续 3 次 → 恰在第 3 次触发
    assert br.note_failure(quota) is False
    assert br.note_failure(quota) is False
    assert br.note_failure(quota) is True
    assert br.tripped is True and br.consecutive == 3
    # 触发后不再累计（保留首次触发证据），成功也不再清零
    assert br.note_failure(quota) is False
    assert br.consecutive == 3
    br.record_success()
    assert br.tripped is True

    msg = br.halt_message()
    assert "provider outage" in msg
    assert "POST /api/research/pipe_outageunit/resume" in msg
    assert "quota" in msg

    snap = br.snapshot()
    assert snap["tripped"] is True
    assert snap["consecutive_failures"] == 3
    assert snap["threshold"] == 3
    assert snap["reason"] == "quota"


def test_registry_register_lookup_clear(monkeypatch, clean_outage_state):
    monkeypatch.setenv("LLM_OUTAGE_HALT_CONSECUTIVE", "4")
    br = po._register_outage_breaker("pipe_outagereg")
    assert br is not None and br.threshold == 4
    assert po._outage_breaker_for("pipe_outagereg") is br
    # 重新注册 = 新 attempt 的新计数器
    br.note_failure(RuntimeError("429"))
    br2 = po._register_outage_breaker("pipe_outagereg")
    assert br2 is not br and br2.consecutive == 0
    po._clear_outage_breaker("pipe_outagereg")
    assert po._outage_breaker_for("pipe_outagereg") is None


# ------------------------------------------------------------------ chat 探针
def _bare_client(provider="minimax", is_fallback=False):
    client = object.__new__(LLMClient)
    client.provider = provider
    client._is_fallback = is_fallback
    return client


def test_probe_counts_fails_fast_and_resets(monkeypatch, clean_outage_state):
    calls = {"n": 0}
    script = ["fail", "fail", "ok", "fail", "fail", "fail"]

    def fake_chat(self, messages, **kwargs):
        calls["n"] += 1
        if script.pop(0) == "fail":
            raise RuntimeError("429 rate limit / quota exhausted")
        return "ok"

    monkeypatch.setattr(LLMClient, "chat", fake_chat)
    assert po._install_llm_outage_probe() is True
    assert getattr(LLMClient.chat, "_drf_outage_probe", False) is True
    assert po._install_llm_outage_probe() is True  # 幂等：不二次包装
    assert LLMClient.chat._drf_outage_probe_orig is fake_chat

    monkeypatch.setenv("LLM_OUTAGE_HALT_CONSECUTIVE", "3")
    breaker = po._register_outage_breaker("pipe_outageprobe")
    tel.set_run_context("pipe_outageprobe")
    try:
        client = _bare_client()
        # 2 连败：计数、未触发
        for _ in range(2):
            with pytest.raises(RuntimeError):
                client.chat([{"role": "user", "content": "q"}])
        assert breaker.consecutive == 2 and breaker.tripped is False
        # 成功清零
        assert client.chat([{"role": "user", "content": "q"}]) == "ok"
        assert breaker.consecutive == 0
        # 3 连败 → tripped
        for _ in range(3):
            with pytest.raises(RuntimeError):
                client.chat([{"role": "user", "content": "q"}])
        assert breaker.tripped is True
        # tripped 后：快速失败，不再发起任何真实调用
        n_before = calls["n"]
        with pytest.raises(RuntimeError) as ei:
            client.chat([{"role": "user", "content": "q"}])
        assert po._PROVIDER_OUTAGE_FAST_FAIL_PREFIX in str(ei.value)
        assert calls["n"] == n_before
    finally:
        tel.set_run_context(None)


def test_probe_skips_fallback_client_and_pierces_cancellation(
        monkeypatch, clean_outage_state):
    behavior = {"exc": po.PipelineCancelled("取消穿透")}

    def fake_chat(self, messages, **kwargs):
        raise behavior["exc"]

    monkeypatch.setattr(LLMClient, "chat", fake_chat)
    po._install_llm_outage_probe()
    monkeypatch.setenv("LLM_OUTAGE_HALT_CONSECUTIVE", "1")
    breaker = po._register_outage_breaker("pipe_outagefb")
    tel.set_run_context("pipe_outagefb")
    try:
        # PipelineCancelled 原样穿透且不计数
        with pytest.raises(po.PipelineCancelled):
            _bare_client().chat([{"role": "user", "content": "q"}])
        assert breaker.consecutive == 0 and breaker.tripped is False

        # 回退客户端（_is_fallback）不计数：其失败已由外层主调用统一计一次
        behavior["exc"] = RuntimeError("429 quota")
        with pytest.raises(RuntimeError, match="429"):
            _bare_client(is_fallback=True).chat([{"role": "user", "content": "q"}])
        assert breaker.consecutive == 0 and breaker.tripped is False

        # 主客户端同一失败计数并触发（threshold=1）；此后回退客户端仍不受快速失败拦截
        with pytest.raises(RuntimeError, match="429"):
            _bare_client().chat([{"role": "user", "content": "q"}])
        assert breaker.tripped is True
        with pytest.raises(RuntimeError, match="429"):
            _bare_client(is_fallback=True).chat([{"role": "user", "content": "q"}])
    finally:
        tel.set_run_context(None)


def test_probe_transparent_without_breaker(monkeypatch, clean_outage_state):
    """未注册熔断器（旋钮关闭/无在飞 run）→ 探针完全透传（legacy 行为）。"""
    def fake_chat(self, messages, **kwargs):
        raise RuntimeError("429 quota exhausted")

    monkeypatch.setattr(LLMClient, "chat", fake_chat)
    po._install_llm_outage_probe()
    with pytest.raises(RuntimeError, match="429"):
        _bare_client().chat([{"role": "user", "content": "q"}])
    # 无归属 → 什么都没注册、什么都没计


def test_current_breaker_attribution(monkeypatch, clean_outage_state):
    monkeypatch.setenv("LLM_OUTAGE_HALT_CONSECUTIVE", "5")
    br_a = po._register_outage_breaker("pipe_outattr_a")
    # 单一注册 + 无 run 上下文 → 注册表单例回退
    tel.set_run_context(None)
    assert po._current_outage_breaker() is br_a
    # 显式 run 上下文 → 精确归属
    tel.set_run_context("pipe_outattr_a")
    try:
        assert po._current_outage_breaker() is br_a
    finally:
        tel.set_run_context(None)
    # 两个熔断器且无上下文 → 归属含糊 → None（宁可不计数也不跨 run 污染）
    po._register_outage_breaker("pipe_outattr_b")
    tel._clear_active_runs()
    assert po._current_outage_breaker() is None


# ------------------------------------------------------- 进度回调止损 + 终态
def test_stage_updater_halts_on_tripped_breaker(
        monkeypatch, tmp_path, clean_outage_state):
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setenv("LLM_OUTAGE_HALT_CONSECUTIVE", "2")
    pid = "pipe_outagehalt"
    state = po.PipelineState(pipeline_id=pid, prompt="q")
    orch = po.PipelineOrchestrator()
    breaker = po._register_outage_breaker(pid)
    upd = orch._make_stage_updater(state, po.STAGE_ONTOLOGY)

    upd(5, "未触发时正常推进")           # 不抛
    quota = RuntimeError("429 quota exhausted")
    breaker.note_failure(quota)
    breaker.note_failure(quota)
    assert breaker.tripped is True
    with pytest.raises(po.ProviderOutageHalt) as ei:
        upd(6, "熔断触发后的下一次进度回调")
    assert "provider outage" in str(ei.value)
    assert f"POST /api/research/{pid}/resume" in str(ei.value)


def test_halt_transition_lands_failed_resumable_checkpoint(
        monkeypatch, tmp_path, clean_outage_state):
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(Config, "LLM_PROVIDER", "minimax", raising=False)
    monkeypatch.setenv("LLM_OUTAGE_HALT_CONSECUTIVE", "1")
    pid = "pipe_outagetrans"
    state = po.PipelineState(pipeline_id=pid, prompt="q")
    state.current_stage = po.STAGE_REPORT
    breaker = po._register_outage_breaker(pid)
    breaker.note_failure(RuntimeError("APIConnectionError: connection refused"))
    assert breaker.tripped is True

    orch = po.PipelineOrchestrator()
    orch._halt_for_provider_outage(
        state, po.TaskManager(), po.ProviderOutageHalt(breaker.halt_message()))

    # 既有可恢复检查点态：status='failed'（resume() 接受 failed/cancelled）
    assert state.status == "failed"
    assert "provider outage" in (state.error or "")
    assert "minimax" in state.error
    assert f"POST /api/research/{pid}/resume" in state.error
    assert state.stages[po.STAGE_REPORT].status == "failed"

    halt = state.options["provider_outage_halt"]
    assert halt["tripped"] is True
    assert halt["consecutive_failures"] == 1
    assert halt["reason"] == "connection"
    assert halt["provider"] == "minimax"
    assert halt["halted_stage"] == po.STAGE_REPORT
    assert halt["resume"] == f"POST /api/research/{pid}/resume"

    data = po.PipelineManager.load(pid)
    assert data is not None and data["status"] == "failed"
    assert data["options"]["provider_outage_halt"]["tripped"] is True


# ------------------------------------------------- 子进程阶段边界计数 + 关闭
def test_note_provider_stage_failure_boundary_counting(
        monkeypatch, clean_outage_state):
    monkeypatch.setenv("LLM_OUTAGE_HALT_CONSECUTIVE", "5")
    pid = "pipe_outagebnd"
    breaker = po._register_outage_breaker(pid)
    po._note_provider_stage_failure(
        pid, RuntimeError("research lane failed: 429 rate limit"))
    assert breaker.consecutive == 1
    # 非提供方级阶段失败：不计
    po._note_provider_stage_failure(
        pid, RuntimeError("所有并行研究轨均失败，研究阶段失败"))
    assert breaker.consecutive == 1
    # 未注册 run → 安静 no-op
    po._note_provider_stage_failure("pipe_unregistered", RuntimeError("429"))
    # None run id → 安静 no-op
    po._note_provider_stage_failure(None, RuntimeError("429"))


def test_disabled_knob_is_legacy_behavior(
        monkeypatch, tmp_path, clean_outage_state):
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setenv("LLM_OUTAGE_HALT_CONSECUTIVE", "-1")
    pid = "pipe_outageoff"
    assert po._register_outage_breaker(pid) is None
    assert po._outage_breaker_for(pid) is None
    state = po.PipelineState(pipeline_id=pid, prompt="q")
    upd = po.PipelineOrchestrator()._make_stage_updater(state, po.STAGE_ONTOLOGY)
    upd(5, "旋钮关闭：不注册熔断器，永不抬升 ProviderOutageHalt")
    assert state.stages[po.STAGE_ONTOLOGY].progress == 5


# ---- 2026-10-18: resume resets the PROCESS-scoped provider breakers ----
# Observed on pipe_fd2799f3ad41: after a 422/429 cascade, a fresh resume attempt
# fast-failed at its first LLM call because the llm_client process-level cooldown
# kept feeding synthetic circuit_breaker failures into the fresh run breaker.

def test_reset_provider_circuit_breakers_clears_cooldowns_and_fallback_cache():
    from app.utils import llm_client as lc
    import time as _time
    with lc._CB_LOCK:
        lc._CB_STATE["glm"] = {
            "consec": 5.0, "consec429": 5.0,
            "tripped_until": _time.monotonic() + 9999.0,
        }
    lc._FB_AUTH_UNAVAILABLE_UNTIL[("fb", "k")] = _time.monotonic() + 9999.0
    try:
        assert lc._cb_tripped("glm") is True
        lc.reset_provider_circuit_breakers("glm")
        assert lc._cb_tripped("glm") is False
        assert lc._FB_AUTH_UNAVAILABLE_UNTIL == {}
        # Re-arm and clear-all path
        lc._CB_STATE["glm"] = {"consec": 5.0, "tripped_until": _time.monotonic() + 9999.0}
        lc.reset_provider_circuit_breakers()
        assert lc._CB_STATE == {}
    finally:
        with lc._CB_LOCK:
            lc._CB_STATE.clear()
            lc._FB_AUTH_UNAVAILABLE_UNTIL.clear()


# ---- 2026-10-18: orphan reclaimer honors owner liveness over heartbeat residue ----
# A killed backend leaves heartbeats "fresh" for the 120s window; the reclaimer
# withheld recycling and resume refused ("管线仍在运行") until manual cancel.

def test_orphan_is_dead_when_owner_pid_dead_even_with_fresh_heartbeat(monkeypatch):
    import subprocess, time as _time
    from app.services.pipeline_orchestrator import PipelineOrchestrator, PipelineManager
    # a genuinely dead pid: spawn and reap a short-lived child
    child = subprocess.Popen(["/bin/sleep", "0"])
    child.wait()
    now = _time.strftime("%Y-%m-%dT%H:%M:%S+00:00", _time.gmtime())
    state = {
        "pipeline_id": "pipe_orphan_liveness_test", "status": "running",
        "owner_pid": child.pid, "owner_boot_id": "some-other-boot",
        "heartbeat_at": now, "updated_at": now,
    }
    monkeypatch.setattr(
        PipelineManager, "load", classmethod(lambda cls, pid: dict(state)),
    )
    # dead owner + fresh heartbeat → dead (heartbeat is just residue)
    assert PipelineOrchestrator._orphan_is_dead("pipe_orphan_liveness_test", stale_s=120.0) is True

    # live owner + fresh heartbeat stays alive (multi-worker safe)
    live = subprocess.Popen(["/bin/sleep", "30"])
    try:
        state["owner_pid"] = live.pid
        monkeypatch.setattr(
            PipelineManager, "load", classmethod(lambda cls, pid: dict(state)),
        )
        assert PipelineOrchestrator._orphan_is_dead("pipe_orphan_liveness_test", stale_s=120.0) is False
    finally:
        live.kill(); live.wait()
