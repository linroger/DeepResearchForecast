"""ORCHESTRATOR + LLM INFRA 审计修复的针对性测试（R2 wave-2 infra group）。

覆盖：LLM-1/2/3/5/6、RPT-10/14、XRUN-3（llm_client）；TEL-1/XRUN-8（telemetry）；
ORCH-2/3/5/7、RES-1/RES-8 镜像、ORCH-4 接线、XRUN-15（pipeline_orchestrator）；
CFG-1 + wave-1 旗标合并（config）。全部为进程内单元测试，不发任何网络请求。
"""

import json
import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.config import Config
from app.utils import llm_client as lc
from app.utils import telemetry as tel


# ---------------------------------------------------------------- config flags
NEW_FLAGS_AND_DEFAULTS = {
    # CFG-1 幽灵旋钮收编
    "PIPELINE_HEARTBEAT_ENABLED": True,
    "PIPELINE_HEARTBEAT_INTERVAL_S": 30.0,
    "PIPELINE_HEARTBEAT_STALE_S": 120.0,
    "PIPELINE_STALE_S": 300.0,
    "PIPELINE_ETA_CAP_S": 7200.0,
    "PIPELINE_LIVE_ARTIFACTS": True,
    "PIPELINE_PARTIAL_SCAN_EVERY_S": 10.0,
    "PIPELINE_VALIDATE_ARTIFACTS": True,
    "MANIFEST_CAPTURE_VERSIONS": False,
    "PARALLEL_PROFILE_COUNT": 16,
    "EMBED_WARM_AT_RESEARCH": False,
    "VALIDATE_AS_OF_DATE": True,
    "GRAPH_CHUNK_SOURCE": "dossier_only",  # W9-10：默认改 dossier_only（KG 收敛到关键 actor）
    # 本组新增
    "PIPELINE_RECLAIM_PORT_PROBE": True,
    "REPORT_LLM_PREFLIGHT": True,
    "LLM_CLI_ISOLATE_HOOKS": True,
    # 研究组
    "ACTOR_SYNTH_MIN_CONTEXT_CHARS": 3000,
    "RESEARCH_MIN_REPORT_CHARS": 400,
    "RESEARCH_FETCH_ACCOUNTING_V2": True,
    "RESEARCH_ASOF_MAX_LAG_DAYS": 45,
    "RESEARCH_QUALITY_GROUNDING": True,
    "ACTOR_DOSSIER_JUDGE_STRICT": False,
    "RESEARCH_COVERAGE_GATE_STANDARD": False,
    # 本体/准备组
    "ONTOLOGY_SEED_ADAPTIVE_BUDGET": True,
    "SIM_EVENT_REACT_BUFFER": True,
    "SIM_SCHEDULE_CLAMP_ROUNDS": True,
    "SIM_RULE_FALLBACK_STANCE": True,
    "SIM_SEED_POST_VARIANTS": True,
    "PERSONA_FIELD_EXTRACTION": True,
    # 图谱组
    "GRAPH_CHOKEPOINT_PRIORS": False,
    "GRAPH_CHOKEPOINT_MAX_NODES": 1500,
    "GRAPH_PRIORS_ALIAS_FOLD": True,
    "GRAPH_MAX_SKIPPED_RATIO": 0.3,
    "SIM_TIER_FROM_ONTOLOGY": False,
    "GRAPH_QUERY_MAX_CHARS": 0,
    "GRAPH_QUERY_CLAMP_SEMANTIC": True,
    # 运行环组
    "SIM_START_HOUR": 0,
    "SIM_RECENCY_CARRY": False,
    "SIM_TWITTER_MODEL_FREE_FEED": True,
    "SIM_TOOL_ARG_NORMALIZE": True,
    "SIM_IDLE_CLOSE_MIN": 60.0,
    "SIM_LLM_ERROR_RATE_THRESHOLD": 0.5,
    "SIM_RESUME": False,
    "INTERVIEW_TIMEOUT_PER_AGENT": 30.0,
    "SIM_CLI_TOOL_EMULATION": True,
    "SIM_LLM_FALLBACK": True,
    "SIM_MIN_FREE_DISK_GB": 2.0,
    "SIM_STEP_FAILURE_LIMIT": 3,
    # 报告组
    "REPORT_ABORT_ON_LLM_OUTAGE": True,
    "REPORT_SECTION_RETRY_MAX": 2,  # RQ-1 1→2
    "REPORT_SECTION_RETRY_BACKOFF_S": 8.0,
    "REPORT_CRITIQUE_BEFORE_PROSE": True,
    "FORECAST_BINARY_CONTRARIAN": True,
    "FORECAST_SIM_SENSITIVITY": True,
    "FORECAST_BINARY_THEMES": "",
    "REPORT_QUOTE_AUDIT_V2": True,
    "REPORT_COMPACT_RETRIEVAL_QUERY": True,
}


def test_cfg1_all_flags_defined_with_expected_defaults():
    """CFG-1 + wave-1 合并：全部旋钮成为真实 Config 属性（.env 未覆盖时按既定默认）。"""
    missing = [n for n in NEW_FLAGS_AND_DEFAULTS if not hasattr(Config, n)]
    assert not missing, f"config.py 缺定义: {missing}"
    for name, default in NEW_FLAGS_AND_DEFAULTS.items():
        if os.environ.get(name):  # 本机 .env 显式覆盖的跳过取值断言
            continue
        val = getattr(Config, name)
        assert val == default, f"{name}: {val!r} != {default!r}"
        assert isinstance(val, type(default)), f"{name} 类型漂移: {type(val)}"


def test_kg8_component_warn_ratio_lowered():
    if not os.environ.get("GRAPH_COMPONENT_WARN_RATIO"):
        assert Config.GRAPH_COMPONENT_WARN_RATIO == pytest.approx(0.2)


def test_llm6_minimax_native_tools_capability_bit():
    assert Config.PROVIDER_META["minimax"].get("native_tools") is False
    # 其余 openai-compat 提供方缺省 True
    assert Config.PROVIDER_META["openai"].get("native_tools", True) is True


# ---------------------------------------------------------------- llm_client
@pytest.fixture(autouse=True)
def _clean_cb_state():
    lc._CB_STATE.clear()
    yield
    lc._CB_STATE.clear()


def test_llm3_quota_classifier():
    assert lc._is_quota(RuntimeError("Error code: 429 - rate_limit_exceeded"))
    assert lc._is_quota(RuntimeError("insufficient quota"))
    assert lc._is_quota(RuntimeError("Claude AI usage limit reached"))
    assert not lc._is_quota(RuntimeError("connection reset by peer"))


def test_llm3_429_breaker_trips_after_threshold():
    for _ in range(lc._CB_429_THRESHOLD):
        lc._cb_record_429("minimax")
    assert lc._cb_tripped("minimax")
    # 成功后清零两条 streak
    lc._CB_STATE["minimax"]["tripped_until"] = 0.0
    lc._cb_reset("minimax")
    assert lc._CB_STATE["minimax"]["consec429"] == 0.0
    assert not lc._cb_tripped("minimax")


def test_cb_record_422_survives_concurrent_calls(monkeypatch):
    """2026-07-03 live-surfaced: graphiti 的图谱阶段用多线程并发调用 chat()。修复前
    `_cb_record_422` 的 `st["consec"] = st.get(...) + 1` 是无锁读改写——并发场景下的
    经典 lost-update 会让计数器永远追不上 _CB_THRESHOLD，即使连续几十次真实失败也
    从未熔断（一次真实 forecast run 里连续 30 次 minimax 422 从未触发熔断日志）。
    用真实线程（而非仅靠 mock）跑 N 个并发调用，验证锁保护下计数不丢。
    """
    monkeypatch.setattr(lc, "_CB_THRESHOLD", 10_000)  # 避免测试中途触发冷却，只验证计数准确
    n_threads, calls_per_thread = 20, 25
    barrier = threading.Barrier(n_threads)

    def _worker():
        barrier.wait()  # 所有线程同时起跑，最大化竞争窗口
        for _ in range(calls_per_thread):
            lc._cb_record_422("minimax")

    threads = [threading.Thread(target=_worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert lc._CB_STATE["minimax"]["consec"] == n_threads * calls_per_thread


def _minimax_client(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_NATIVE_TOOLS", True, raising=False)
    return lc.LLMClient(provider="minimax", api_key="sk-test",
                        base_url="http://127.0.0.1:1/v1", model="MiniMax-M3")


def test_llm6_rpt10_supports_native_tools_gates(monkeypatch):
    client = _minimax_client(monkeypatch)
    # 能力位 False（PROVIDER_META）→ 拒绝原生工具
    assert client.supports_native_tools() is False
    # 白名单覆盖能力位
    monkeypatch.setenv("LLM_NATIVE_TOOLS_PROVIDERS", "minimax")
    assert client.supports_native_tools() is True
    # RPT-10: 熔断冷却期间即便白名单也拒绝
    lc._CB_STATE["minimax"] = {"consec": 0.0, "tripped_until": time.monotonic() + 60}
    assert client.supports_native_tools() is False


def test_llm1_chat_with_tools_retries_then_raises(monkeypatch):
    client = _minimax_client(monkeypatch)
    calls = {"n": 0}

    class _Boom:
        def create(self, **kwargs):
            calls["n"] += 1
            raise RuntimeError("transient")

    client._openai_client = SimpleNamespace(chat=SimpleNamespace(completions=_Boom()))
    monkeypatch.setattr(lc, "_retry_delay", lambda exc, attempt: 0.0)
    with pytest.raises(RuntimeError, match="transient"):
        client.chat_with_tools([{"role": "user", "content": "hi"}], tools_schema=[])
    assert calls["n"] == lc.MAX_RETRIES  # 重试打满而非单次裸调用


def test_llm1_chat_with_tools_records_422_and_breaker_precheck(monkeypatch):
    client = _minimax_client(monkeypatch)

    class _Filter:
        def create(self, **kwargs):
            raise ValueError("Error code: 422 - new_sensitive")

    client._openai_client = SimpleNamespace(chat=SimpleNamespace(completions=_Filter()))
    with pytest.raises(ValueError):
        client.chat_with_tools([{"role": "user", "content": "hi"}], tools_schema=[])
    assert lc._CB_STATE["minimax"]["consec"] == 1.0
    # 冷却中 → 预检直接抛（不再发注定失败的调用）
    lc._CB_STATE["minimax"]["tripped_until"] = time.monotonic() + 60
    with pytest.raises(RuntimeError, match="熔断冷却"):
        client.chat_with_tools([{"role": "user", "content": "hi"}], tools_schema=[])


def test_llm1_chat_with_tools_meters_usage(monkeypatch):
    client = _minimax_client(monkeypatch)
    usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7)
    msg = SimpleNamespace(content="ok", tool_calls=[])
    resp = SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)
    client._openai_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **k: resp)))
    recorded = []
    monkeypatch.setattr(tel.LLMMeter, "record",
                        classmethod(lambda cls, *a, **k: recorded.append((a, k))))
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", True, raising=False)
    out = client.chat_with_tools([{"role": "user", "content": "hi"}], tools_schema=[])
    assert out["content"] == "ok" and out["tool_calls"] == []
    assert len(recorded) == 1
    args = recorded[0][0]
    assert args[0] == "minimax" and args[2] == 11 and args[3] == 7


def test_llm2_fallback_served_call_not_double_metered(monkeypatch):
    """主提供方失败、回退接管 → 外层不得再按主提供方计量一次。"""
    client = lc.LLMClient(provider="claude-cli")
    monkeypatch.setattr(lc, "_retry_delay", lambda exc, attempt: 0.0)
    monkeypatch.setattr(
        lc.LLMClient, "_chat_claude_cli",
        lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("primary down")))
    monkeypatch.setattr(lc.LLMClient, "_try_fallback", lambda self, *a, **k: "fb-answer")
    recorded = []
    monkeypatch.setattr(tel.LLMMeter, "record",
                        classmethod(lambda cls, *a, **k: recorded.append(a)))
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "LLM_CACHE_ENABLED", False, raising=False)
    out = client.chat([{"role": "user", "content": "q"}])
    assert out == "fb-answer"
    assert recorded == []  # 回退客户端（此处被 mock 掉）才是唯一计量方


def test_xrun3_claude_cli_isolates_hooks_and_reports_rc(monkeypatch):
    client = lc.LLMClient(provider="claude-cli")
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(lc.subprocess, "run", fake_run)
    monkeypatch.setattr(Config, "LLM_CLI_ISOLATE_HOOKS", True, raising=False)
    with pytest.raises(RuntimeError) as ei:
        client._chat_claude_cli([{"role": "user", "content": "hi"}], 0.3, 64)
    # XRUN-3: hooks 隔离进了命令行；LLM-5/RPT-14: 空输出时错误串带 rc + 占位说明
    assert "--settings" in seen["cmd"]
    idx = seen["cmd"].index("--settings")
    assert json.loads(seen["cmd"][idx + 1]) == {"disableAllHooks": True}
    assert "rc=1" in str(ei.value) and "no output" in str(ei.value)


def test_llm5_error_envelope_includes_result_payload(monkeypatch):
    client = lc.LLMClient(provider="claude-cli")
    envelope = json.dumps({"is_error": True, "subtype": "error",
                           "result": "Claude AI usage limit reached"})
    monkeypatch.setattr(
        lc.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=envelope, stderr=""))
    with pytest.raises(RuntimeError, match="usage limit reached"):
        client._chat_claude_cli([{"role": "user", "content": "hi"}], 0.3, 64)


def test_llm3_fallback_openai_client_pool_cached(monkeypatch):
    """回退提供方的 OpenAI 连接池跨调用复用（LLMClient 实例仍新建）。"""
    lc._FB_OPENAI_CLIENTS.clear()
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "minimax")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "MiniMax-M3")
    captured = []
    orig_chat = lc.LLMClient.chat

    def fake_chat(self, *a, **k):
        captured.append(self._openai_client)
        return "fb"

    monkeypatch.setattr(lc.LLMClient, "chat", fake_chat)
    primary = lc.LLMClient(provider="claude-cli")
    try:
        assert primary._try_fallback([{"role": "user", "content": "q"}], 0.3, 64, None,
                                     RuntimeError("x")) == "fb"
        assert primary._try_fallback([{"role": "user", "content": "q"}], 0.3, 64, None,
                                     RuntimeError("y")) == "fb"
    finally:
        monkeypatch.setattr(lc.LLMClient, "chat", orig_chat)
    assert len(captured) == 2 and captured[0] is captured[1]
    lc._FB_OPENAI_CLIENTS.clear()


def test_cli_auth_failure_is_not_retried(monkeypatch):
    """A deterministic 401 must not incur the generic three-attempt backoff."""
    monkeypatch.delenv("LLM_FALLBACK_PROVIDER", raising=False)
    client = lc.LLMClient(provider="claude-cli")
    calls = {"n": 0}

    def fail_auth(*_args, **_kwargs):
        calls["n"] += 1
        raise RuntimeError(
            'Claude CLI failed: {"api_error_status":401,'
            '"result":"Failed to authenticate. Invalid authentication credentials"}'
        )

    monkeypatch.setattr(client, "_chat_claude_cli", fail_auth)
    monkeypatch.setattr(
        lc,
        "_retry_delay",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not retry")),
    )
    with pytest.raises(RuntimeError, match="Failed to authenticate"):
        client.chat([{"role": "user", "content": "q"}])
    assert calls["n"] == 1


def test_fallback_auth_failure_enters_process_cooldown(monkeypatch):
    """Parallel calls must not repeatedly invoke a fallback with broken credentials."""
    lc._FB_AUTH_UNAVAILABLE_UNTIL.clear()
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "claude-cli")
    monkeypatch.delenv("LLM_FALLBACK_MODEL", raising=False)
    monkeypatch.delenv("LLM_FALLBACK_BASE_URL", raising=False)
    calls = {"n": 0}

    def fail_auth(self, *_args, **_kwargs):
        calls["n"] += 1
        raise RuntimeError("Failed to authenticate. API Error: 401 Invalid authentication credentials")

    monkeypatch.setattr(lc.LLMClient, "chat", fail_auth)
    primary = lc.LLMClient(provider="minimax", api_key="sk-test",
                           base_url="http://127.0.0.1:1/v1", model="MiniMax-M3")
    args = ([{"role": "user", "content": "q"}], 0.3, 64, None,
            RuntimeError("primary timed out"))
    assert primary._try_fallback(*args) is None
    assert primary._try_fallback(*args) is None
    assert calls["n"] == 1
    lc._FB_AUTH_UNAVAILABLE_UNTIL.clear()


def test_antigravity_fallback_uses_own_reasoning_contract(monkeypatch):
    """Antigravity fallback gets low effort without inheriting MiniMax's extra_body."""
    captured = {}

    class _Completions:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            message = SimpleNamespace(content="READY")
            choice = SimpleNamespace(message=message, finish_reason="stop")
            return SimpleNamespace(choices=[choice], usage=None)

    client = object.__new__(lc.LLMClient)
    client.provider = "antigravity"
    client.model = "gemini-3-flash-preview"
    client._openai_client = SimpleNamespace(
        chat=SimpleNamespace(completions=_Completions())
    )
    client._fast_openai_client = None
    client._is_fallback = True
    client._last_usage = None
    monkeypatch.setattr(Config, "LLM_PROVIDER", "minimax", raising=False)
    # Match production: tiering stays on and the global strong model conflicts
    # with Quotio's alias. The fallback client must still own its model.
    monkeypatch.setattr(Config, "LLM_TIERED_ROUTING", True, raising=False)
    monkeypatch.setattr(Config, "LLM_STRONG_MODEL", "MiniMax-M3", raising=False)
    monkeypatch.setenv("LLM_FALLBACK_REASONING_EFFORT", "low")

    assert client._chat_openai(
        [{"role": "user", "content": "Reply READY only."}], 0.1, 32
    ) == "READY"
    assert captured["model"] == "gemini-3-flash-preview"
    assert captured["reasoning_effort"] == "low"
    assert "extra_body" not in captured


def test_antigravity_fallback_fast_tier_keeps_quotio_endpoint(monkeypatch):
    """Fast routing must never replace a resolved fallback client's endpoint."""
    primary_calls = []
    decoy_calls = []

    def response_for(calls):
        class _Completions:
            @staticmethod
            def create(**kwargs):
                calls.append(kwargs)
                message = SimpleNamespace(content="READY", tool_calls=[])
                choice = SimpleNamespace(message=message, finish_reason="stop")
                return SimpleNamespace(choices=[choice], usage=None)

        return SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))

    client = object.__new__(lc.LLMClient)
    client.provider = "antigravity"
    client.model = "gemini-3-flash-preview"
    client._openai_client = response_for(primary_calls)
    client._fast_openai_client = response_for(decoy_calls)
    client._is_fallback = True
    client._last_usage = None
    monkeypatch.setattr(Config, "LLM_TIERED_ROUTING", True, raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_PROVIDER", "minimax", raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_MODEL", "MiniMax-M3", raising=False)
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", False, raising=False)
    monkeypatch.setattr(Config, "LLM_RUN_BUDGET_TOKENS", 0, raising=False)
    monkeypatch.setattr(Config, "LLM_RUN_BUDGET_USD", 0.0, raising=False)
    monkeypatch.setenv("LLM_FALLBACK_REASONING_EFFORT", "low")

    assert client._chat_openai(
        [{"role": "user", "content": "Reply READY only."}],
        0.1,
        32,
        tier="fast",
    ) == "READY"
    tool_result = client.chat_with_tools(
        [{"role": "user", "content": "Reply READY only."}],
        [{
            "type": "function",
            "function": {
                "name": "noop",
                "description": "No operation",
                "parameters": {"type": "object", "properties": {}},
            },
        }],
        max_tokens=32,
        tier="fast",
    )

    # INFRA-1 added finish_reason / served_model as additive keys of the returned dict.
    assert tool_result == {"content": "READY", "tool_calls": [],
                           "finish_reason": "stop", "served_model": None}
    assert [row["model"] for row in primary_calls] == [
        "gemini-3-flash-preview", "gemini-3-flash-preview",
    ]
    assert decoy_calls == []


def test_antigravity_is_a_fallback_only_quotio_provider():
    """Backend failover preserves Antigravity identity without exposing it as primary."""
    assert "antigravity" in lc.OPENAI_COMPATIBLE_PROVIDERS
    assert "antigravity" not in Config.PROVIDER_META

    client = lc.LLMClient(
        provider="antigravity",
        api_key="quotio-local-test",
        base_url="http://127.0.0.1:8320/v1",
        model="gemini-3-flash-preview",
    )
    try:
        assert client.provider == "antigravity"
        assert client._openai_client is not None
    finally:
        close = getattr(client._openai_client, "close", None)
        if callable(close):
            close()


# ---------------------------------------------------------------- telemetry
def test_xrun8_cost_basis_subscription_vs_mixed():
    rid = "test_cost_basis_run"
    tel.LLMMeter.reset(rid)
    tel.LLMMeter.record("claude-cli", "opus", 100, 50, 10.0, run_id=rid, stage="report")
    assert tel.LLMMeter.snapshot(rid)["cost_basis"] == "subscription"
    tel.LLMMeter.record("minimax", "MiniMax-M3", 100, 50, 10.0, run_id=rid, stage="report")
    assert tel.LLMMeter.snapshot(rid)["cost_basis"] == "mixed"
    tel.LLMMeter.reset(rid)


def test_xrun8_write_run_telemetry_merges_previous_attempt(tmp_path):
    rid = "test_merge_run"
    path = str(tmp_path / "run_telemetry.json")
    tel.LLMMeter.reset(rid)
    tel.LLMMeter.record("minimax", "M3", 10, 5, 1.0, run_id=rid, stage="graph")
    tel.LLMMeter.write_run_telemetry(path, run_id=rid, extra={"report_id": "report_a", "status": "failed"})
    tel.LLMMeter.reset(rid)
    tel.LLMMeter.record("minimax", "M3", 20, 10, 1.0, run_id=rid, stage="report")
    tel.LLMMeter.write_run_telemetry(path, run_id=rid, extra={"report_id": "report_b", "status": "completed"})
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["report_id"] == "report_b"
    assert data["previous_attempt"]["report_id"] == "report_a"
    assert data["cumulative_total"]["total_tokens"] == 45  # 15 + 30
    tel.LLMMeter.reset(rid)


def test_tel1_global_bucket_leak_warning():
    # mirofish.* logger 不向 root 传播（app 日志配置），直接挂临时 handler 捕获。
    records = []

    class _Cap(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    lg = logging.getLogger("mirofish.telemetry")
    h = _Cap(level=logging.WARNING)
    lg.addHandler(h)
    try:
        tel.LLMMeter._runs.pop("_global", None)
        # FOG-TEL-1 contract update: unattributed records now fall back to the sole
        # active run when exactly one is registered; the '_global' leak warning only
        # fires when attribution is genuinely ambiguous (zero or 2+ active runs).
        # Clear this thread's context + the registry so the test exercises the
        # genuinely-unattributed path regardless of suite order.
        tel.set_run_context(None, None)
        tel._clear_active_runs()
        for _ in range(20):
            tel.LLMMeter.record("minimax", "M3", 1, 1, 0.1, run_id=None, stage=None)
    finally:
        lg.removeHandler(h)
        tel.LLMMeter._runs.pop("_global", None)
    assert any("_global" in m for m in records)


# ---------------------------------------------------------------- orchestrator
from app.services import pipeline_orchestrator as po  # noqa: E402


def test_res8_degraded_dossier_gate():
    assert po._is_degraded_dossier("short") is True                       # <400 chars
    assert po._is_degraded_dossier("x" * 500 + " new_sensitive ") is True  # 错误串
    assert po._is_degraded_dossier("正常卷宗内容。" * 100) is False
    assert po._is_degraded_dossier("") is False  # 空=缺失，交由原有语义


def test_orch2_orphan_grace_when_owner_and_heartbeat_missing(monkeypatch):
    now = datetime.now(timezone.utc)
    fresh = {"pipeline_id": "pipe_x", "status": "running",
             "updated_at": now.isoformat()}
    stale = {"pipeline_id": "pipe_x", "status": "running",
             "updated_at": (now - timedelta(seconds=999)).isoformat()}
    monkeypatch.setattr(po.PipelineManager, "load", classmethod(lambda cls, pid: dict(fresh)))
    assert po.PipelineOrchestrator._orphan_is_dead("pipe_x", 120.0) is False  # 有宽限
    monkeypatch.setattr(po.PipelineManager, "load", classmethod(lambda cls, pid: dict(stale)))
    assert po.PipelineOrchestrator._orphan_is_dead("pipe_x", 120.0) is True


def test_xrun15_mark_failed_preserves_completed_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path), raising=False)
    pid = "pipe_deadbeef0001"
    os.makedirs(tmp_path / pid / "handoff", exist_ok=True)
    state = {
        "pipeline_id": pid, "status": "running", "current_stage": "ontology",
        "schema_version": po.PIPELINE_SCHEMA_VERSION, "artifacts": {},
        "stages": {"ontology": {"name": "ontology", "status": "running",
                                "progress": 100, "message": "本体生成完成"}},
    }
    (tmp_path / pid / "pipeline_state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8")
    assert po.PipelineManager.mark_failed(pid, "已被用户取消", status="cancelled")
    saved = json.loads((tmp_path / pid / "pipeline_state.json").read_text(encoding="utf-8"))
    assert saved["status"] == "cancelled"
    # 100% 的阶段不再被改写成 cancelled（曾出现 cancelled+progress=100+'完成' 的矛盾标签）
    assert saved["stages"]["ontology"]["status"] == "completed"


def test_orch7_eta_anchor_prefers_resumed_at():
    state = po.PipelineState(
        pipeline_id="pipe_eta", prompt="q", mode="full", status="running",
        global_progress=50,
    )
    state.created_at = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    state.options["resumed_at"] = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    out = po.PipelineOrchestrator().estimate_eta(state)
    assert out["elapsed_s"] is not None and out["elapsed_s"] < 3600  # 不再按 3 天外推


def test_orch3_resume_completed_requires_force(monkeypatch):
    data = {"pipeline_id": "pipe_done", "status": "completed",
            "schema_version": po.PIPELINE_SCHEMA_VERSION,
            "options": {"pipeline_health": {"status": "degraded"}}}
    monkeypatch.setattr(po.PipelineManager, "load", classmethod(lambda cls, pid: dict(data)))
    monkeypatch.setattr(po.PipelineOrchestrator, "_threads", {})
    with pytest.raises(RuntimeError, match="force"):
        po.PipelineOrchestrator.resume("pipe_done", force=False)
    # 健康 ok 的 completed 即便 force 也拒绝
    data_ok = dict(data, options={"pipeline_health": {"status": "ok"}})
    monkeypatch.setattr(po.PipelineManager, "load", classmethod(lambda cls, pid: dict(data_ok)))
    with pytest.raises(RuntimeError, match="管线已完成"):
        po.PipelineOrchestrator.resume("pipe_done", force=True)


def test_orch3_resume_message_names_upstream_degradation(monkeypatch):
    """force only regenerates the report: when only an upstream stage (e.g. RESEARCH-2's
    research stage) is degraded, the refusal says a force-resume cannot fix it."""
    monkeypatch.setattr(po.PipelineOrchestrator, "_threads", {})

    def _refusal(stages):
        data = {"pipeline_id": "pipe_done", "status": "completed",
                "schema_version": po.PIPELINE_SCHEMA_VERSION,
                "options": {"pipeline_health": {"status": "degraded", "stages": stages}}}
        monkeypatch.setattr(po.PipelineManager, "load", classmethod(lambda cls, pid: dict(data)))
        with pytest.raises(RuntimeError) as exc:
            po.PipelineOrchestrator.resume("pipe_done", force=False)
        return str(exc.value)

    upstream = _refusal({"research": {"health": "degraded", "issues": ["x"]}})
    assert "research" in upstream and "无法修复" in upstream and "请带 force=true 重试" not in upstream
    report = _refusal({"research": {"health": "degraded"}, "report": {"health": "degraded"}})
    assert "请带 force=true 重试" in report


def test_orch4_ensemble_wired_into_run():
    """ORCH-4: _maybe_run_seed_ensemble 除定义外必须有 _run 内的真实调用点。"""
    src = open(po.__file__, encoding="utf-8").read()
    assert src.count("_maybe_run_seed_ensemble(") >= 2  # def + call site


def test_ont2_template_none_passed_to_generator():
    src = open(po.__file__, encoding="utf-8").read()
    assert "template=Config.ONTOLOGY_TEMPLATE" not in src
    assert "template=None" in src


def test_kg5_graph_degraded_folded_into_pipeline_health(monkeypatch):
    orch = po.PipelineOrchestrator()
    state = po.PipelineState(pipeline_id="pipe_h", prompt="q", mode="full", status="running")
    state.options["graph_ingest_degraded_ratio"] = 0.5
    state.options["graph_skipped_chunks"] = 5
    state.options["graph_total_chunks"] = 10
    monkeypatch.setattr(po.PipelineOrchestrator, "_assess_report_health",
                        lambda self, rid: ("ok", [], {}))
    monkeypatch.setattr(Config, "PIPELINE_HEALTH_GATE", True, raising=False)
    orch._enforce_pipeline_health(state)
    ph = state.options["pipeline_health"]
    assert ph["stages"]["graph"]["health"] == "degraded"
    assert ph["status"] == "degraded"


def test_loop003_prune_postcondition_degrades_pipeline_health(monkeypatch):
    orch = po.PipelineOrchestrator()
    state = po.PipelineState(pipeline_id="pipe_prune", prompt="q", mode="full", status="running")
    state.options["graph_prune"] = {
        "degraded": True,
        "postcondition_ok": False,
        "actual_after": 610,
        "effective_cap": 400,
        "error": "graph pruning postcondition failed: actual graph exceeds effective hard cap",
    }
    monkeypatch.setattr(po.PipelineOrchestrator, "_assess_report_health",
                        lambda self, rid: ("ok", [], {}))
    monkeypatch.setattr(Config, "PIPELINE_HEALTH_GATE", True, raising=False)

    orch._enforce_pipeline_health(state)

    ph = state.options["pipeline_health"]
    assert ph["status"] == "degraded"
    assert ph["stages"]["graph"]["health"] == "degraded"
    assert "exceeds effective hard cap" in ph["stages"]["graph"]["issues"][0]
    assert ph["stages"]["graph"]["prune"]["actual_after"] == 610


def test_xrun11_run_health_prefers_run_summary(tmp_path, monkeypatch):
    sim_id = "sim_test_health"
    # sqlite/run_state 目录（_sim_dir）与 run_summary 目录（RUN_STATE_DIR）分别打桩
    monkeypatch.setattr(po.PipelineOrchestrator, "_sim_dir",
                        staticmethod(lambda s: str(tmp_path / "simdir")))
    monkeypatch.setattr(po.SimulationRunner, "RUN_STATE_DIR", str(tmp_path / "runstate"), raising=False)
    os.makedirs(tmp_path / "runstate" / sim_id, exist_ok=True)
    (tmp_path / "runstate" / sim_id / "run_summary.json").write_text(json.dumps({
        "organic_action_count": 40, "simulation_health": "llm_degraded"}), encoding="utf-8")
    health, issues, meta = po.PipelineOrchestrator()._assess_run_health(sim_id)
    assert meta["organic_actions"] == 40 and meta["organic_source"] == "run_summary"
    assert any("llm_degraded" in i for i in issues)
    assert health == "degraded"
