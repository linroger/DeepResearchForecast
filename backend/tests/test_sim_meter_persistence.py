"""DEFECT-3：模拟子进程的 token 计量落盘 + 编排器恰好一次入账。

审计取证：648 次已确认的 LLM 调用在 run_telemetry.json 里记为 0 token——oasis_llm
为每次调用构造 usage（CLI/回退路径按文本长度估算、直连路径为提供方真实值），但喂给
camel 后即被丢弃；决策通道/in-band 演化的 LLMMeter 记录只活在子进程内存里，进程退出
整场账蒸发。覆盖：

- 子进程侧累计器：模型边界（_wrap_model_llm_counter）逐调用提取 usage，真实
  （source='provider'）与伪造估算（source='estimate'，id 前缀 'chatcmpl-cli-'）分桶，
  无 usage → 'missing'；既有 counter dict 契约（{"calls","errors"} 精确形状）不变；
- LLMClient 包装（决策通道/in-band 路径）：精确 _last_usage 优先，缺失时长度估算；
- sim_llm_telemetry.json 原子快照：字段、meter_run_token（幂等去重键）、provider 解析、
  失败路径（__main__ finally）照写；
- 重跑轮转：sim_llm_telemetry.json 随 _rotate_stale_action_logs 一并轮转；
- 编排器 _record_sim_run_telemetry：恰好一次（同 token 重入/跨 attempt 复用跳过；
  新 token 的重跑照记）、stage='run' 合成记录、provider/model 映射、零 token 跳过、
  计量关闭仅 stash、失败边界同样恰好一次落账；
- 子进程写 → 编排器读的端到端字段兼容。

全部离线：零网络、零真实 LLM、零真实子进程。
"""

import asyncio
import json
import os
import sys
from types import SimpleNamespace

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_BACKEND, "scripts")
for _p in (_BACKEND, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_parallel_simulation as rps  # noqa: E402

from app.config import Config  # noqa: E402
from app.services import pipeline_orchestrator as po  # noqa: E402
from app.services.simulation_runner import SimulationRunner  # noqa: E402
from app.utils.telemetry import LLMMeter  # noqa: E402

SIM_ID = "sim_meter_fixture"


# ------------------------------------------------------------------ fixtures
@pytest.fixture
def fresh_usage(monkeypatch):
    """进程级累计器隔离：每测一个全新 dict（helpers 经模块名解引用，setattr 即生效）。"""
    fresh = {"calls": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0,
             "by_source": {}, "by_model": {}}
    monkeypatch.setattr(rps, "_SIM_LLM_USAGE", fresh)
    return fresh


@pytest.fixture
def meter_run():
    created = []

    def _make(run_id):
        created.append(run_id)
        LLMMeter.reset(run_id)
        return run_id

    yield _make
    for rid in created:
        LLMMeter.reset(rid)


@pytest.fixture
def orch_env(monkeypatch, tmp_path):
    """编排器侧隔离：RUN_STATE_DIR + PIPELINE_DATA_DIR + 计量开。"""
    root = tmp_path / "simulations"
    (root / SIM_ID).mkdir(parents=True)
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(root))
    monkeypatch.setattr(SimulationRunner, "_run_states", {})
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"),
                        raising=False)
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", True, raising=False)
    return str(root / SIM_ID)


def _completion(pt=100, ct=40, cid="chatcmpl-real-1", model="MiniMax-M3"):
    return SimpleNamespace(
        id=cid, model=model,
        usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct,
                              total_tokens=pt + ct),
    )


def _write_snapshot(sim_dir, **overrides):
    payload = {
        "schema_version": "sim-llm-telemetry/v1",
        "simulation_id": SIM_ID,
        "meter_run_token": "tok_attempt_1",
        "provider": "minimax",
        "model": "MiniMax-M3",
        "calls": 648,
        "errors": 2,
        "prompt_tokens": 120000,
        "completion_tokens": 45000,
        "total_tokens": 165000,
        "by_source": {"provider": {"calls": 600, "prompt_tokens": 110000,
                                   "completion_tokens": 41000},
                      "estimate": {"calls": 48, "prompt_tokens": 10000,
                                   "completion_tokens": 4000}},
        "wall_s": 2880.0,
    }
    payload.update(overrides)
    with open(os.path.join(sim_dir, "sim_llm_telemetry.json"), "w",
              encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return payload


# ---------------------------------------------------- 子进程侧：来源分桶
def test_accumulator_separates_provider_and_estimate_sources(fresh_usage):
    rps._accumulate_sim_llm_response(_completion(100, 40, cid="chatcmpl-real-1"))
    rps._accumulate_sim_llm_response(
        _completion(30, 10, cid="chatcmpl-cli-abcdef", model="claude-cli"))
    rps._accumulate_sim_llm_response(
        SimpleNamespace(id="x", model="m", usage=None))

    u = rps._SIM_LLM_USAGE
    assert u["calls"] == 3
    assert u["prompt_tokens"] == 130 and u["completion_tokens"] == 50
    assert u["by_source"]["provider"] == {
        "calls": 1, "prompt_tokens": 100, "completion_tokens": 40}
    assert u["by_source"]["estimate"] == {
        "calls": 1, "prompt_tokens": 30, "completion_tokens": 10}
    assert u["by_source"]["missing"]["calls"] == 1
    assert u["by_model"]["MiniMax-M3"]["calls"] == 1
    assert u["by_model"]["claude-cli"]["calls"] == 1


def test_accumulator_never_raises_on_garbage(fresh_usage):
    rps._accumulate_sim_llm_response(None)
    rps._accumulate_sim_llm_response({"ok": True})
    rps._accumulate_sim_llm_response(
        SimpleNamespace(id=None, model=None,
                        usage=SimpleNamespace(prompt_tokens="junk",
                                              completion_tokens=None)))
    assert rps._SIM_LLM_USAGE["calls"] >= 2  # 垃圾输入也只是记 0-token 调用，不炸


def test_wrap_model_counter_accumulates_usage_and_keeps_contract(fresh_usage):
    """模型边界包装：usage 进累计器，counter dict 保持 {"calls","errors"} 精确形状
    （test_audit_fixes_runloop 的既有契约按 dict 相等断言）。"""
    class FakeModel:
        behavior = ["ok", "fail", "ok"]

        async def _arequest_chat_completion(self, messages, tools=None):
            if self.behavior.pop(0) == "fail":
                raise ValueError("boom")
            return _completion(50, 20)

    model = FakeModel()
    counter = rps._wrap_model_llm_counter(model)

    async def _drive():
        await model._arequest_chat_completion([])
        with pytest.raises(ValueError):
            await model._arequest_chat_completion([])
        await model._arequest_chat_completion([])

    asyncio.run(_drive())
    assert counter == {"calls": 3, "errors": 1}  # 契约不变（无新键）
    u = rps._SIM_LLM_USAGE
    assert u["calls"] == 2 and u["errors"] == 1
    assert u["prompt_tokens"] == 100 and u["completion_tokens"] == 40
    assert u["by_source"]["provider"]["calls"] == 2


def test_wrap_llm_client_provider_usage_preferred(fresh_usage):
    class FakeClient:
        provider = "minimax"
        model = "MiniMax-M3"
        _last_usage = None

        def chat(self, messages, **kwargs):
            self._last_usage = {"prompt_tokens": 800, "completion_tokens": 150}
            return "batch decision text"

    client = rps._wrap_llm_client_usage(FakeClient())
    assert client.chat([{"role": "user", "content": "q"}]) == "batch decision text"
    u = rps._SIM_LLM_USAGE
    assert u["by_source"]["provider"] == {
        "calls": 1, "prompt_tokens": 800, "completion_tokens": 150}
    assert u["by_model"]["MiniMax-M3"]["calls"] == 1


def test_wrap_llm_client_estimates_when_no_usage(fresh_usage):
    class FakeCLIClient:
        provider = "claude-cli"
        model = ""
        _last_usage = None

        def chat_json(self, messages, **kwargs):
            return {"commitments": ["scenario_a"] * 10}

    client = rps._wrap_llm_client_usage(FakeCLIClient())
    client.chat_json([{"role": "user", "content": "x" * 400}])
    u = rps._SIM_LLM_USAGE
    est = u["by_source"]["estimate"]
    assert est["calls"] == 1
    assert est["prompt_tokens"] > 0 and est["completion_tokens"] > 0


def test_wrap_llm_client_counts_errors_and_reraises(fresh_usage):
    class Broken:
        provider = "minimax"
        model = "m"
        _last_usage = None

        def chat(self, messages, **kwargs):
            raise RuntimeError("429 quota")

    client = rps._wrap_llm_client_usage(Broken())
    with pytest.raises(RuntimeError, match="429"):
        client.chat([])
    assert rps._SIM_LLM_USAGE["errors"] == 1
    assert rps._SIM_LLM_USAGE["calls"] == 0


# ---------------------------------------------------- 子进程侧：快照落盘
def test_write_snapshot_fields_and_token(fresh_usage, tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    rps._accumulate_sim_llm_response(_completion(100, 40))
    rps._accumulate_sim_llm_response(
        _completion(30, 10, cid="chatcmpl-cli-x", model="claude-cli"))
    rps._write_sim_llm_telemetry(str(tmp_path), {"simulation_id": SIM_ID})

    with open(tmp_path / "sim_llm_telemetry.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data["schema_version"] == "sim-llm-telemetry/v1"
    assert data["simulation_id"] == SIM_ID
    assert data["provider"] == "minimax"
    assert data["model"] in ("MiniMax-M3", "claude-cli")  # 主导模型（并列取其一）
    assert data["calls"] == 2 and data["errors"] == 0
    assert data["prompt_tokens"] == 130 and data["completion_tokens"] == 50
    assert data["total_tokens"] == 180
    assert data["by_source"]["provider"]["calls"] == 1
    assert data["by_source"]["estimate"]["calls"] == 1
    assert data["meter_run_token"] == rps._SIM_LLM_METER_RUN_TOKEN
    assert data["wall_s"] >= 0

    # 幂等重写：同进程 token 不变（编排器据此去重）。
    rps._write_sim_llm_telemetry(str(tmp_path), {"simulation_id": SIM_ID})
    with open(tmp_path / "sim_llm_telemetry.json", encoding="utf-8") as f:
        again = json.load(f)
    assert again["meter_run_token"] == data["meter_run_token"]


def test_write_snapshot_on_failure_path_with_zero_calls(fresh_usage, tmp_path):
    """失败路径（__main__ finally）：即使一发调用都没打出去也照写快照（诚实的 0 账）。"""
    rps._write_sim_llm_telemetry(str(tmp_path), None)
    with open(tmp_path / "sim_llm_telemetry.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data["calls"] == 0 and data["total_tokens"] == 0


def test_main_exit_wiring_writes_snapshot_in_finally():
    """__main__ 出口接线特征化：finally 块里挂 _write_sim_llm_telemetry（失败/中断/
    信号退出路径都不丢账），且 main() 尽早钉定落盘目标。"""
    with open(os.path.join(_SCRIPTS, "run_parallel_simulation.py"),
              encoding="utf-8") as f:
        src = f.read()
    i_main_guard = src.index('if __name__ == "__main__":')
    tail = src[i_main_guard:]
    i_finally = tail.index("finally:")
    assert "_write_sim_llm_telemetry(" in tail[i_finally:]
    assert '_SIM_LLM_TELEMETRY_SINK["dir"] = simulation_dir' in src
    # 模拟回路结束后（进入命令等待模式之前）也先落一版。
    i_loop_done = src.index("模拟循环完成! 总耗时")  # main() 的双平台收束点
    i_early_write = src.index("_write_sim_llm_telemetry(simulation_dir, config",
                              i_loop_done)
    assert i_early_write < src.index("进入等待命令模式 - 环境保持运行", i_loop_done)


def test_rotate_stale_artifacts_rotates_snapshot(tmp_path, monkeypatch):
    """重跑前上一轮的 token 快照必须轮转——防止新一轮启动即失败时旧账被再次消费。"""
    sim_dir = tmp_path / SIM_ID
    sim_dir.mkdir()
    (sim_dir / "sim_llm_telemetry.json").write_text("{}", encoding="utf-8")
    SimulationRunner._rotate_stale_action_logs(str(sim_dir))
    assert not (sim_dir / "sim_llm_telemetry.json").exists()
    assert (sim_dir / "sim_llm_telemetry.json.prev").exists()


# ---------------------------------------------------- 编排器侧：恰好一次入账
def test_orchestrator_lands_run_stage_record_exactly_once(orch_env, meter_run):
    run_id = meter_run("pipe_simmeter1")
    _write_snapshot(orch_env)
    state = po.PipelineState(pipeline_id=run_id, prompt="q")
    orch = po.PipelineOrchestrator()

    orch._record_sim_run_telemetry(state, SIM_ID)
    snap = LLMMeter.snapshot(run_id)
    run_row = snap["by_stage"]["run"]
    assert run_row["calls"] == 1                       # 一条合成记录
    assert run_row["prompt_tokens"] == 120000
    assert run_row["completion_tokens"] == 45000
    assert "minimax:MiniMax-M3" in snap["by_model"]

    # 重入（同一边界被再次触达 / 复用路径）→ 同 token 跳过，无双计。
    orch._record_sim_run_telemetry(state, SIM_ID)
    snap = LLMMeter.snapshot(run_id)
    assert snap["by_stage"]["run"]["calls"] == 1
    assert snap["total"]["calls"] == 1

    stash = state.options["sim_llm_telemetry"]
    assert stash["calls"] == 648 and stash["total_tokens"] == 165000
    assert stash["by_source"]["estimate"]["calls"] == 48
    marker = state.options["sim_llm_telemetry_recorded"]
    assert marker["simulation_id"] == SIM_ID
    assert marker["meter_run_token"] == "tok_attempt_1"


def test_orchestrator_skips_after_prior_attempt_marker(orch_env, meter_run):
    """resume 复用路径：上一 attempt 已入账（marker 随 pipeline_state 持久化）→
    本 attempt 的边界调用跳过（上一 attempt 的账经 run_telemetry 合并基底延续）。"""
    run_id = meter_run("pipe_simmeter2")
    _write_snapshot(orch_env)
    state = po.PipelineState(pipeline_id=run_id, prompt="q")
    state.options["sim_llm_telemetry_recorded"] = {
        "simulation_id": SIM_ID, "meter_run_token": "tok_attempt_1",
        "recorded_at": "2026-07-15T00:00:00Z"}
    po.PipelineOrchestrator()._record_sim_run_telemetry(state, SIM_ID)
    assert LLMMeter.snapshot(run_id)["total"]["calls"] == 0


def test_rerun_with_new_token_records_the_new_spend(orch_env, meter_run):
    """重跑（rotation 后新子进程 = 新 meter_run_token）是新一笔真实花费 → 照记。"""
    run_id = meter_run("pipe_simmeter3")
    _write_snapshot(orch_env)
    state = po.PipelineState(pipeline_id=run_id, prompt="q")
    orch = po.PipelineOrchestrator()
    orch._record_sim_run_telemetry(state, SIM_ID)
    _write_snapshot(orch_env, meter_run_token="tok_attempt_2",
                    prompt_tokens=5000, completion_tokens=2000,
                    total_tokens=7000, calls=30)
    orch._record_sim_run_telemetry(state, SIM_ID)
    snap = LLMMeter.snapshot(run_id)
    assert snap["by_stage"]["run"]["calls"] == 2
    assert snap["by_stage"]["run"]["prompt_tokens"] == 125000
    assert state.options["sim_llm_telemetry_recorded"]["meter_run_token"] == "tok_attempt_2"


def test_failed_sim_snapshot_lands_exactly_once_at_failure_boundary(
        orch_env, meter_run):
    """失败模拟：子进程 finally 已落盘快照 → 失败边界（except BaseException 钩子）
    入账恰好一次；随后 resume 重跑前的任何重入不双计。"""
    run_id = meter_run("pipe_simmeter4")
    _write_snapshot(orch_env, meter_run_token="tok_failed_attempt",
                    calls=210, prompt_tokens=40000, completion_tokens=9000,
                    total_tokens=49000)
    state = po.PipelineState(pipeline_id=run_id, prompt="q")
    orch = po.PipelineOrchestrator()
    orch._record_sim_run_telemetry(state, SIM_ID)   # 失败边界
    orch._record_sim_run_telemetry(state, SIM_ID)   # 冗余重入
    snap = LLMMeter.snapshot(run_id)
    assert snap["by_stage"]["run"]["calls"] == 1
    assert snap["by_stage"]["run"]["prompt_tokens"] == 40000


def test_zero_token_snapshot_marks_but_records_nothing(orch_env, meter_run):
    run_id = meter_run("pipe_simmeter5")
    _write_snapshot(orch_env, calls=3, prompt_tokens=0, completion_tokens=0,
                    total_tokens=0)
    state = po.PipelineState(pipeline_id=run_id, prompt="q")
    po.PipelineOrchestrator()._record_sim_run_telemetry(state, SIM_ID)
    assert LLMMeter.snapshot(run_id)["total"]["calls"] == 0
    # 已核销（marker 落下）：不再反复重读同一份空账。
    assert state.options["sim_llm_telemetry_recorded"]["meter_run_token"] == "tok_attempt_1"


def test_missing_snapshot_is_silent_noop(orch_env, meter_run):
    run_id = meter_run("pipe_simmeter6")
    state = po.PipelineState(pipeline_id=run_id, prompt="q")
    po.PipelineOrchestrator()._record_sim_run_telemetry(state, SIM_ID)
    assert LLMMeter.snapshot(run_id)["total"]["calls"] == 0
    assert "sim_llm_telemetry_recorded" not in state.options


def test_telemetry_disabled_stashes_without_meter_record(
        orch_env, meter_run, monkeypatch):
    run_id = meter_run("pipe_simmeter7")
    _write_snapshot(orch_env)
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", False, raising=False)
    state = po.PipelineState(pipeline_id=run_id, prompt="q")
    po.PipelineOrchestrator()._record_sim_run_telemetry(state, SIM_ID)
    assert LLMMeter.snapshot(run_id)["total"]["calls"] == 0
    assert state.options["sim_llm_telemetry"]["calls"] == 648  # 免费观测仍在


def test_cli_model_fallback_provider_mapping(orch_env, meter_run):
    """快照缺 provider 时按研究路径同款映射兜底：claude/codex → claude-cli（0 成本）。"""
    run_id = meter_run("pipe_simmeter8")
    _write_snapshot(orch_env, provider="", model="claude",
                    prompt_tokens=100, completion_tokens=50, total_tokens=150)
    state = po.PipelineState(pipeline_id=run_id, prompt="q")
    po.PipelineOrchestrator()._record_sim_run_telemetry(state, SIM_ID)
    snap = LLMMeter.snapshot(run_id)
    assert "claude-cli:claude" in snap["by_model"]
    assert snap["total"]["cost_usd"] == 0


def test_subprocess_writer_to_orchestrator_roundtrip(
        fresh_usage, orch_env, meter_run, monkeypatch):
    """端到端字段兼容：子进程 writer 落盘 → 编排器读同一文件入账。"""
    run_id = meter_run("pipe_simmeter9")
    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    rps._accumulate_sim_llm_response(_completion(700, 300))
    rps._write_sim_llm_telemetry(orch_env, {"simulation_id": SIM_ID})

    state = po.PipelineState(pipeline_id=run_id, prompt="q")
    po.PipelineOrchestrator()._record_sim_run_telemetry(state, SIM_ID)
    snap = LLMMeter.snapshot(run_id)
    assert snap["by_stage"]["run"]["calls"] == 1
    assert snap["by_stage"]["run"]["prompt_tokens"] == 700
    assert snap["by_stage"]["run"]["completion_tokens"] == 300
    assert "minimax:MiniMax-M3" in snap["by_model"]
    assert (state.options["sim_llm_telemetry_recorded"]["meter_run_token"]
            == rps._SIM_LLM_METER_RUN_TOKEN)


# ------------------------------------------- EVAL-17：种子模拟计量 + 按模拟键的标记
SEED_SIM_ID = "sim_seed_fixture"


def _write_sim_snapshot(root, sim_id, **overrides):
    sim_dir = os.path.join(root, sim_id)
    os.makedirs(sim_dir, exist_ok=True)
    overrides.setdefault("simulation_id", sim_id)
    return _write_snapshot(sim_dir, **overrides)


def test_main_and_seed_each_recorded_once(orch_env, meter_run):
    """Main sim under 'run', seed sim under 'ensemble_sim'; a seed recording neither evicts
    the main marker (re-entry stays a no-op) nor overwrites the main-run stash."""
    run_id = meter_run("pipe_eval17_both")
    root = os.path.dirname(orch_env)
    _write_snapshot(orch_env)                               # main: 120000/45000
    _write_sim_snapshot(root, SEED_SIM_ID, meter_run_token="tok_seed_1", calls=90,
                        prompt_tokens=30000, completion_tokens=7000, total_tokens=37000)
    state = po.PipelineState(pipeline_id=run_id, prompt="q")
    orch = po.PipelineOrchestrator()

    orch._record_sim_run_telemetry(state, SIM_ID)
    orch._record_sim_run_telemetry(state, SEED_SIM_ID, stage=po.SIM_METER_STAGE_ENSEMBLE)
    # Re-entry for both (success boundary, resume reuse path, redundant finally).
    orch._record_sim_run_telemetry(state, SIM_ID)
    orch._record_sim_run_telemetry(state, SEED_SIM_ID, stage=po.SIM_METER_STAGE_ENSEMBLE)

    snap = LLMMeter.snapshot(run_id)
    assert snap["by_stage"]["run"]["calls"] == 1
    assert snap["by_stage"]["run"]["prompt_tokens"] == 120000
    assert snap["by_stage"]["ensemble_sim"]["calls"] == 1
    assert snap["by_stage"]["ensemble_sim"]["prompt_tokens"] == 30000
    assert snap["by_stage"]["ensemble_sim"]["completion_tokens"] == 7000
    assert snap["total"]["calls"] == 2

    markers = state.options[po.SIM_METER_MARKERS_OPTION]
    assert markers[SIM_ID]["meter_run_token"] == "tok_attempt_1"
    assert markers[SIM_ID]["stage"] == "run"
    assert markers[SEED_SIM_ID] == {"meter_run_token": "tok_seed_1", "stage": "ensemble_sim",
                                    "recorded_at": markers[SEED_SIM_ID]["recorded_at"]}
    assert markers[SEED_SIM_ID]["recorded_at"]
    # The stash and the legacy mirror stay the main run's (a seed never writes them).
    assert state.options["sim_llm_telemetry"]["calls"] == 648
    assert state.options["sim_llm_telemetry_recorded"]["simulation_id"] == SIM_ID


def test_seed_then_main_order_does_not_double_count_main(orch_env, meter_run):
    """Pre-EVAL-17 a single slot would let a seed recording evict the main marker; the
    main sim's later boundary call then double counted it. The per-sim map prevents it."""
    run_id = meter_run("pipe_eval17_order")
    root = os.path.dirname(orch_env)
    _write_snapshot(orch_env)
    _write_sim_snapshot(root, SEED_SIM_ID, meter_run_token="tok_seed_1")
    state = po.PipelineState(pipeline_id=run_id, prompt="q")
    orch = po.PipelineOrchestrator()
    orch._record_sim_run_telemetry(state, SIM_ID)
    orch._record_sim_run_telemetry(state, SEED_SIM_ID, stage=po.SIM_METER_STAGE_ENSEMBLE)
    orch._record_sim_run_telemetry(state, SIM_ID)
    assert LLMMeter.snapshot(run_id)["by_stage"]["run"]["calls"] == 1


def test_legacy_marker_honoured_and_migrated(orch_env, meter_run):
    """A run persisted before EVAL-17 carries only the single slot: it is honoured (no
    re-record of the main sim), migrated into the map, and a new seed still records."""
    run_id = meter_run("pipe_eval17_legacy")
    root = os.path.dirname(orch_env)
    _write_snapshot(orch_env)
    _write_sim_snapshot(root, SEED_SIM_ID, meter_run_token="tok_seed_1")
    state = po.PipelineState(pipeline_id=run_id, prompt="q")
    legacy = {"simulation_id": SIM_ID, "meter_run_token": "tok_attempt_1",
              "recorded_at": "2026-07-15T00:00:00Z"}
    state.options["sim_llm_telemetry_recorded"] = dict(legacy)
    orch = po.PipelineOrchestrator()

    orch._record_sim_run_telemetry(state, SIM_ID)
    assert LLMMeter.snapshot(run_id)["total"]["calls"] == 0
    assert state.options[po.SIM_METER_MARKERS_OPTION] == {
        SIM_ID: {"meter_run_token": "tok_attempt_1", "stage": "run",
                 "recorded_at": "2026-07-15T00:00:00Z"}}
    # The migration is persisted with the state (a resumed attempt reloads it).
    persisted = po.PipelineManager.load(run_id)
    assert SIM_ID in persisted["options"][po.SIM_METER_MARKERS_OPTION]

    orch._record_sim_run_telemetry(state, SEED_SIM_ID, stage=po.SIM_METER_STAGE_ENSEMBLE)
    orch._record_sim_run_telemetry(state, SIM_ID)
    snap = LLMMeter.snapshot(run_id)
    assert snap["total"]["calls"] == 1
    assert "run" not in snap["by_stage"]
    assert snap["by_stage"]["ensemble_sim"]["calls"] == 1
    assert state.options["sim_llm_telemetry_recorded"] == legacy  # seed left it alone


def test_legacy_marker_honoured_when_map_is_stale(orch_env, meter_run):
    """Rollback safety: older code re-ran the main sim and advanced only the legacy slot;
    the stale map entry must not make the new code record that run a second time."""
    run_id = meter_run("pipe_eval17_stale")
    _write_snapshot(orch_env, meter_run_token="tok_attempt_2")
    state = po.PipelineState(pipeline_id=run_id, prompt="q")
    state.options[po.SIM_METER_MARKERS_OPTION] = {
        SIM_ID: {"meter_run_token": "tok_attempt_1", "stage": "run", "recorded_at": "t1"}}
    state.options["sim_llm_telemetry_recorded"] = {
        "simulation_id": SIM_ID, "meter_run_token": "tok_attempt_2", "recorded_at": "t2"}
    po.PipelineOrchestrator()._record_sim_run_telemetry(state, SIM_ID)
    assert LLMMeter.snapshot(run_id)["total"]["calls"] == 0


def test_concurrent_seed_recordings_lock(orch_env, meter_run, monkeypatch):
    """Seed threads record concurrently (ENSEMBLE_SEED_CONCURRENCY <= 3): the check-and-mark
    runs under _sim_meter_lock, so each simulation lands exactly once and no marker is lost."""
    import threading
    import time as _time

    run_id = meter_run("pipe_eval17_conc")
    root = os.path.dirname(orch_env)
    seeds = [f"sim_seed_c{i}" for i in range(3)]
    for i, sid in enumerate(seeds):
        _write_sim_snapshot(root, sid, meter_run_token=f"tok_c{i}",
                            prompt_tokens=1000 * (i + 1), completion_tokens=100)
    inside = {"now": 0, "max": 0}
    guard = threading.Lock()
    real_read = po._read_json

    def slow_read(path):
        # Widen the read-check-write window so a missing lock would interleave.
        with guard:
            inside["now"] += 1
            inside["max"] = max(inside["max"], inside["now"])
        try:
            _time.sleep(0.02)
            return real_read(path)
        finally:
            with guard:
                inside["now"] -= 1

    monkeypatch.setattr(po, "_read_json", slow_read)
    state = po.PipelineState(pipeline_id=run_id, prompt="q")
    orch = po.PipelineOrchestrator()
    start = threading.Barrier(len(seeds) * 3)

    def worker(sid):
        start.wait()
        orch._record_sim_run_telemetry(state, sid, stage=po.SIM_METER_STAGE_ENSEMBLE)

    threads = [threading.Thread(target=worker, args=(sid,)) for sid in seeds for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert inside["max"] == 1                         # serialised
    row = LLMMeter.snapshot(run_id)["by_stage"]["ensemble_sim"]
    assert row["calls"] == 3                          # each seed exactly once
    assert row["prompt_tokens"] == 1000 + 2000 + 3000
    assert set(state.options[po.SIM_METER_MARKERS_OPTION]) == set(seeds)
    assert "sim_llm_telemetry" not in state.options
    assert "sim_llm_telemetry_recorded" not in state.options


# ------------------------------- EVAL-17：_maybe_run_seed_ensemble 端到端（真实 _run_one_seed）
_PRIMARY_FORECAST = {"scenarios": [
    {"name": "A", "probability": 0.6, "resolution_criteria": "a"},
    {"name": "B", "probability": 0.4, "resolution_criteria": "b"}]}


def _seed_ensemble_harness(monkeypatch, tmp_path, run_id, *, sim_outcome="completed"):
    """N_FORECAST_SEEDS=2 with the real _maybe_run_seed_ensemble/_run_one_seed; only the
    simulation manager/runner and the report agent are stubbed. The stub runner writes the
    seed's sim_llm_telemetry.json the way the simulation subprocess does."""
    root = tmp_path / "simulations"
    root.mkdir(exist_ok=True)
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"), raising=False)
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "N_FORECAST_SEEDS", 2, raising=False)
    monkeypatch.setattr(Config, "ENSEMBLE_SEED_CONCURRENCY", 1, raising=False)
    monkeypatch.setattr(Config, "REPORT_STRUCTURED_FORECAST", True, raising=False)
    monkeypatch.setattr(Config, "SIM_GRAPH_FEEDBACK", False, raising=False)
    monkeypatch.setattr(Config, "SIM_SEED", 0, raising=False)

    class _Sim:
        simulation_id = SEED_SIM_ID

    class _SimManager:
        def create_simulation(self, *a, **k):
            return _Sim()

        def prepare_simulation(self, **k):
            return None

    class _RunState:
        current_round = 1
        runner_status = (po.RunnerStatus.COMPLETED if sim_outcome == "completed"
                         else po.RunnerStatus.FAILED)

    class _Runner:
        RUN_STATE_DIR = str(root)

        @staticmethod
        def start_simulation(simulation_id, **k):
            _write_sim_snapshot(str(root), simulation_id, meter_run_token="tok_seed_run",
                                calls=77, prompt_tokens=21000, completion_tokens=6000,
                                total_tokens=27000)

        get_run_state = staticmethod(lambda sim_id: _RunState())
        write_run_summary = staticmethod(lambda sim_id: None)
        stop_simulation = staticmethod(lambda sim_id: None)

    class _FakeAgent:
        def __init__(self, **kwargs):
            self.ledger_context = None

        def generate_report(self, report_id=None, **kw):
            if sim_outcome == "report_fails":
                raise RuntimeError("seed report failed")

    monkeypatch.setattr(po, "SimulationManager", _SimManager)
    monkeypatch.setattr(po, "SimulationRunner", _Runner)
    monkeypatch.setattr(po, "ReportAgent", _FakeAgent)
    monkeypatch.setattr(po.PipelineOrchestrator, "_read_report_forecast",
                        staticmethod(lambda rid: _PRIMARY_FORECAST if rid == "report_main"
                                     else None))
    handoff = tmp_path / "handoff"
    handoff.mkdir(exist_ok=True)
    state = po.PipelineState(pipeline_id=run_id, prompt="q", mode="full",
                             report_id="report_main", handoff_dir=str(handoff))
    return state


def _run_ensemble(orch, state):
    import contextvars
    # A copied context keeps the run/stage context the ensemble sets out of later tests.
    contextvars.copy_context().run(
        orch._maybe_run_seed_ensemble, state, type("P", (), {"project_id": "proj"})(),
        "graph_1", None, {"sources": []}, "# report")


def test_seed_ensemble_meters_seed_sim_under_ensemble_sim(monkeypatch, tmp_path, meter_run):
    """Acceptance: with N_FORECAST_SEEDS=2, run_telemetry.json by_stage.ensemble_sim equals the
    seed's sim_llm_telemetry.json, and the main sim is recorded exactly once across a resume."""
    run_id = meter_run("pipe_eval17_ens")
    state = _seed_ensemble_harness(monkeypatch, tmp_path, run_id)
    _write_sim_snapshot(str(tmp_path / "simulations"), SIM_ID)   # main: 120000/45000

    orch = po.PipelineOrchestrator()
    orch._init_telemetry_flush(state)
    orch._record_sim_run_telemetry(state, SIM_ID)                # main RUN boundary
    _run_ensemble(orch, state)

    tel = json.loads((tmp_path / "pipelines" / run_id / "run_telemetry.json")
                     .read_text(encoding="utf-8"))
    with open(tmp_path / "simulations" / SEED_SIM_ID / "sim_llm_telemetry.json",
              encoding="utf-8") as f:
        seed_snapshot = json.load(f)
    ens = tel["by_stage"]["ensemble_sim"]
    assert ens["calls"] == 1
    assert ens["prompt_tokens"] == seed_snapshot["prompt_tokens"] == 21000
    assert ens["completion_tokens"] == seed_snapshot["completion_tokens"] == 6000
    assert ens["total_tokens"] == seed_snapshot["total_tokens"]
    assert tel["by_stage"]["run"]["prompt_tokens"] == 120000
    assert state.options[po.SIM_METER_MARKERS_OPTION][SEED_SIM_ID]["stage"] == "ensemble_sim"
    assert state.options["ensemble_member_simulations"] == {SEED_SIM_ID: 7919 * 2}

    # Resume in a fresh process: meter cleared, state reloaded, the RUN reuse boundary
    # re-enters for the same main simulation (same meter_run_token on disk).
    LLMMeter.reset(run_id)
    resumed = po.PipelineState.from_dict(po.PipelineManager.load(run_id))
    orch2 = po.PipelineOrchestrator()
    orch2._init_telemetry_flush(resumed)
    orch2._record_sim_run_telemetry(resumed, SIM_ID)
    orch2._flush_run_telemetry(resumed, final=True)
    tel2 = json.loads((tmp_path / "pipelines" / run_id / "run_telemetry.json")
                      .read_text(encoding="utf-8"))
    assert tel2["total"]["calls"] == 0                            # nothing re-recorded
    assert tel2["cumulative_by_stage"]["run"]["calls"] == 1
    assert tel2["cumulative_by_stage"]["run"]["prompt_tokens"] == 120000
    assert tel2["cumulative_by_stage"]["ensemble_sim"]["prompt_tokens"] == 21000


@pytest.mark.parametrize("outcome", ["sim_fails", "report_fails"])
def test_seed_failure_path_records(monkeypatch, tmp_path, meter_run, outcome):
    """A seed whose simulation or report fails has still burnt its simulation tokens: the
    finally around _run_one_seed meters them once; the ensemble skips the seed as before."""
    run_id = meter_run(f"pipe_eval17_fail_{outcome}")
    state = _seed_ensemble_harness(monkeypatch, tmp_path, run_id, sim_outcome=outcome)
    orch = po.PipelineOrchestrator()
    orch._init_telemetry_flush(state)
    _run_ensemble(orch, state)

    snap = LLMMeter.snapshot(run_id)
    assert snap["by_stage"]["ensemble_sim"]["calls"] == 1
    assert snap["by_stage"]["ensemble_sim"]["prompt_tokens"] == 21000
    assert state.options[po.SIM_METER_MARKERS_OPTION][SEED_SIM_ID]["meter_run_token"] \
        == "tok_seed_run"
    assert state.options["ensemble_done"] is True                 # seed skipped, as before


def test_seed_cancel_path_records(monkeypatch, tmp_path, meter_run):
    """Cancellation inside the seed's poll loop propagates, and the seed spend is metered."""
    run_id = meter_run("pipe_eval17_cancel")
    state = _seed_ensemble_harness(monkeypatch, tmp_path, run_id)
    import threading

    ev = threading.Event()

    class _CancellingRunner(po.SimulationRunner):
        @staticmethod
        def get_run_state(sim_id):
            ev.set()  # the cancel lands while the seed is polling
            return SimpleNamespace(current_round=0, runner_status=po.RunnerStatus.RUNNING)

    monkeypatch.setattr(po, "SimulationRunner", _CancellingRunner)
    monkeypatch.setattr(po.time, "sleep", lambda _s: None)
    monkeypatch.setitem(po.PipelineOrchestrator._cancel_events, run_id, ev)
    orch = po.PipelineOrchestrator()
    with pytest.raises(po.PipelineCancelled):
        _run_ensemble(orch, state)
    snap = LLMMeter.snapshot(run_id)
    assert snap["by_stage"]["ensemble_sim"]["calls"] == 1
    assert snap["by_stage"]["ensemble_sim"]["completion_tokens"] == 6000


def test_seed_without_simulation_records_nothing(monkeypatch, tmp_path, meter_run):
    """create_simulation itself failing leaves no simulation to meter: nothing is recorded."""
    run_id = meter_run("pipe_eval17_nosim")
    state = _seed_ensemble_harness(monkeypatch, tmp_path, run_id)

    class _BrokenManager:
        def create_simulation(self, *a, **k):
            raise RuntimeError("no simulation")

    monkeypatch.setattr(po, "SimulationManager", _BrokenManager)
    _run_ensemble(po.PipelineOrchestrator(), state)
    assert LLMMeter.snapshot(run_id)["total"]["calls"] == 0
    assert po.SIM_METER_MARKERS_OPTION not in state.options


def test_default_single_seed_runs_no_seed_and_meters_nothing(monkeypatch, tmp_path, meter_run):
    """The pinned default N_FORECAST_SEEDS=1 never reaches the seed path: no seed
    simulation, no ensemble_sim record, no marker map (behaviour as before)."""
    run_id = meter_run("pipe_eval17_n1")
    state = _seed_ensemble_harness(monkeypatch, tmp_path, run_id)
    monkeypatch.setattr(Config, "N_FORECAST_SEEDS", 1, raising=False)
    _run_ensemble(po.PipelineOrchestrator(), state)
    assert LLMMeter.snapshot(run_id)["by_stage"] == {}
    assert po.SIM_METER_MARKERS_OPTION not in state.options
    assert not (tmp_path / "simulations" / SEED_SIM_ID).exists()


# ------------------------------------------- EVAL-17：cumulative_by_stage 跨 attempt
def test_cumulative_by_stage_across_two_attempts(tmp_path, monkeypatch, meter_run):
    """Acceptance: a two-attempt pipeline reports cumulative_by_stage = attempt 1 + attempt 2
    per stage (base fixed at the attempt start, repeated flushes never re-add)."""
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path), raising=False)
    run_id = meter_run("pipe_eval17_cum")
    (tmp_path / run_id).mkdir()
    state = po.PipelineState(pipeline_id=run_id, prompt="q")

    orch1 = po.PipelineOrchestrator()
    orch1._init_telemetry_flush(state)
    LLMMeter.record("minimax", "m", 1000, 200, 10.0, run_id=run_id, stage="research",
                    prompt_cache_read_tokens=600)
    LLMMeter.record("minimax", "m", 300, 50, 5.0, run_id=run_id, stage="report")
    orch1._flush_run_telemetry(state, final=True)
    first = json.loads((tmp_path / run_id / "run_telemetry.json").read_text("utf-8"))
    assert "cumulative_by_stage" not in first            # first attempt: shape unchanged
    assert "cumulative_total" not in first

    LLMMeter.reset(run_id)                               # process restart
    orch2 = po.PipelineOrchestrator()
    orch2._init_telemetry_flush(state)
    LLMMeter.record("minimax", "m", 400, 100, 4.0, run_id=run_id, stage="report")
    orch2._flush_run_telemetry(state)                    # in-flight flush
    LLMMeter.record("minimax", "m", 700, 70, 7.0, run_id=run_id, stage="run")
    orch2._flush_run_telemetry(state, final=True)
    data = json.loads((tmp_path / run_id / "run_telemetry.json").read_text("utf-8"))

    cum = data["cumulative_by_stage"]
    assert set(cum) == {"research", "report", "run"}
    for stage in cum:
        for key in ("calls", "cached", "prompt_tokens", "completion_tokens", "total_tokens",
                    "latency_ms", "cost_usd", "prompt_cache_read_tokens"):
            expected = ((first["by_stage"].get(stage) or {}).get(key, 0)
                        + (data["by_stage"].get(stage) or {}).get(key, 0))
            assert cum[stage][key] == pytest.approx(expected), (stage, key)
    assert cum["report"]["calls"] == 2 and cum["report"]["prompt_tokens"] == 700
    assert cum["research"]["prompt_cache_read_tokens"] == 600
    assert data["cumulative_total"]["calls"] == 4
    assert data["cumulative_total"]["prompt_cache_read_tokens"] == 600
    assert sum(row["calls"] for row in cum.values()) == data["cumulative_total"]["calls"]

    # Attempt 3 builds on attempt 2's cumulative_by_stage, not just its by_stage.
    LLMMeter.reset(run_id)
    orch3 = po.PipelineOrchestrator()
    orch3._init_telemetry_flush(state)
    LLMMeter.record("minimax", "m", 10, 1, 1.0, run_id=run_id, stage="report")
    orch3._flush_run_telemetry(state, final=True)
    third = json.loads((tmp_path / run_id / "run_telemetry.json").read_text("utf-8"))
    assert third["cumulative_by_stage"]["report"]["calls"] == 3
    assert third["cumulative_by_stage"]["research"]["calls"] == 1
    assert third["cumulative_total"]["calls"] == 5


def test_cumulative_by_stage_falls_back_to_legacy_by_stage(tmp_path, monkeypatch, meter_run):
    """A run_telemetry.json written before EVAL-17 has no cumulative_by_stage: its by_stage
    is the per-stage base."""
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path), raising=False)
    run_id = meter_run("pipe_eval17_cumlegacy")
    (tmp_path / run_id).mkdir()
    prev = {"total": {"calls": 2, "prompt_tokens": 50, "completion_tokens": 5,
                      "total_tokens": 55},
            "by_stage": {"graph": {"calls": 2, "prompt_tokens": 50, "completion_tokens": 5,
                                   "total_tokens": 55}}}
    (tmp_path / run_id / "run_telemetry.json").write_text(json.dumps(prev), encoding="utf-8")
    state = po.PipelineState(pipeline_id=run_id, prompt="q")
    orch = po.PipelineOrchestrator()
    orch._init_telemetry_flush(state)
    LLMMeter.record("minimax", "m", 10, 1, 1.0, run_id=run_id, stage="graph")
    orch._flush_run_telemetry(state, final=True)
    data = json.loads((tmp_path / run_id / "run_telemetry.json").read_text("utf-8"))
    assert data["cumulative_by_stage"]["graph"]["calls"] == 3
    assert data["cumulative_by_stage"]["graph"]["prompt_tokens"] == 60
    assert data["cumulative_by_stage"]["graph"]["prompt_cache_read_tokens"] == 0
