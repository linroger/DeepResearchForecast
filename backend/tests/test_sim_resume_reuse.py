"""DEFECT-1/DEFECT-2：resume 不再重跑已完成的模拟；hollow rc=0 运行按阶段失败处理。

取证背景（2026-07-15）：一场 18 轮模拟被 resume 对着耗尽的提供方配额重跑 4 次、损失
3h34m——sim 目录里明明躺着一份完整的已完成运行（actions.jsonl 带 simulation_end、
派生产物齐全），但 RUN stage 位在崩溃/重启窗口被抹掉后，编排器无条件重启子进程。
bug-sweep 另发现：子进程可以 rc=0 退出却从未产出 simulation_end，下游把它当成功消费。

覆盖：
- _completed_sim_reusable 探测器：密封配置 + 完成标记 + 有效 run_summary → 可复用；
  旋钮关闭 / hollow（无 simulation_end）/ seal 篡改 / 无 seal 身份 / 半写 run_summary /
  身份不匹配 → 一律 fail closed 照旧重跑；
- 后端重启窗口：run_state 停在 RUNNING/FAILED 而 actions.jsonl 已有 simulation_end
  （detached 子进程干净收尾）→ 仍判定可复用；
- 复用判定期间绝不重启子进程（stub/spy runner）；
- DEFECT-2 完成证据门：缺 simulation_end 完成标记 / run_summary 无效 → RuntimeError
  （清晰讯息、可 resume），证据齐全 → 放行；
- _run 接线特征化（与 test_foglamp_containment 的 getsource 先例同构）：探测在
  start_simulation 之前、门在 _complete_stage(STAGE_RUN) 之前、复用路径不重启子进程。

全部离线：零网络、零真实 LLM、零真实子进程。
"""

import hashlib
import inspect
import json
import os

import pytest

from app.config import Config
from app.services import pipeline_orchestrator as po
from app.services.simulation_manager import (
    SimulationState,
    SimulationStatus,
    build_simulation_config_seal,
)
from app.services.simulation_runner import RunnerStatus, SimulationRunner

SIM_ID = "sim_reuse_fixture"


# ------------------------------------------------------------------ fixtures
@pytest.fixture
def isolated_runner(monkeypatch, tmp_path):
    """隔离 RUN_STATE_DIR + 清空 runner 进程内注册表（防跨测试串档）。"""
    root = tmp_path / "simulations"
    root.mkdir()
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(root))
    monkeypatch.setattr(SimulationRunner, "_run_states", {})
    monkeypatch.setattr(SimulationRunner, "_run_state_last_save", {})
    monkeypatch.setattr(SimulationRunner, "_processes", {})
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"),
                        raising=False)
    monkeypatch.delenv("SIM_RESUME_REUSE_COMPLETED", raising=False)
    monkeypatch.setattr(Config, "SIM_RESUME_REUSE_COMPLETED", True, raising=False)
    return str(root)


def _write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _append_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _build_completed_sim(root, *, with_end=True, with_summary=True,
                         run_state_status="completed", run_state_completed=True):
    """在隔离 RUN_STATE_DIR 里搭一场「密封配置 + 已完成」的模拟现场。

    复用 test_simulation_config_seal 的密封配方（cast/context/role 闭包 + config seal），
    再补上运行证据：双平台 actions.jsonl（可选 simulation_end）、run_state.json、
    run_summary.json。返回 (sim_state, config_sha, manifest_sha)。
    """
    sim_dir = os.path.join(root, SIM_ID)
    os.makedirs(sim_dir, exist_ok=True)
    cast = os.path.join(sim_dir, "actor_cast_manifest.json")
    context = os.path.join(sim_dir, "actor_context_manifest.json")
    reddit_roles = os.path.join(sim_dir, "reddit_profiles_roles.json")
    twitter_roles = os.path.join(sim_dir, "twitter_profiles_roles.json")
    _write_json(os.path.join(sim_dir, "simulation_config.json"), {
        "simulation_id": SIM_ID,
        "agent_configs": [{"agent_id": 0, "stance": "neutral"}],
    })
    _write_json(cast, {"selected_actor_count": 1})
    _write_json(context, {"schema_version": "actor-context-manifest/v1"})
    for role_path in (reddit_roles, twitter_roles):
        _write_json(role_path, {
            "role_contract_version": "actor-role/v2",
            "actor_context_required": True,
            "actor_role_count": 1,
        })
    config_sha, manifest_sha = build_simulation_config_seal(
        sim_dir,
        simulation_id=SIM_ID,
        actor_cast_manifest_sha256=_sha(cast),
        actor_context_manifest_sha256=_sha(context),
        actor_role_manifest_sha256={
            "reddit": _sha(reddit_roles), "twitter": _sha(twitter_roles)},
    )

    for platform in ("twitter", "reddit"):
        rows = [
            {"event_type": "simulation_start", "timestamp": "t0"},
            {"round": 1, "agent_id": 0, "agent_name": "A",
             "action_type": "CREATE_POST", "action_args": {}},
            {"event_type": "round_end", "round": 1, "simulated_hours": 1},
        ]
        if with_end:
            rows.append({"event_type": "simulation_end",
                         "total_rounds": 18, "total_actions": 42})
        _append_jsonl(os.path.join(sim_dir, platform, "actions.jsonl"), rows)

    _write_json(os.path.join(sim_dir, "run_state.json"), {
        "simulation_id": SIM_ID,
        "runner_status": run_state_status,
        "current_round": 18,
        "total_rounds": 18,
        "twitter_enabled": True,
        "reddit_enabled": True,
        "twitter_completed": run_state_completed,
        "reddit_completed": run_state_completed,
        "completed_at": "2026-07-15T00:00:00" if run_state_completed else None,
    })
    if with_summary:
        _write_json(os.path.join(sim_dir, "run_summary.json"), {
            "simulation_id": SIM_ID,
            "rounds_executed": 18,
            "agents": [],
        })

    sim_state = SimulationState(
        simulation_id=SIM_ID, project_id="p1", graph_id="g1",
        status=SimulationStatus.COMPLETED,
        simulation_config_sha256=config_sha,
        simulation_config_manifest_sha256=manifest_sha,
    )
    return sim_state, config_sha, manifest_sha


def _pipeline_state():
    state = po.PipelineState(pipeline_id="pipe_simreuse", prompt="q")
    state.simulation_id = SIM_ID
    return state


# ------------------------------------------------------- DEFECT-1: 探测器
def test_completed_sealed_sim_is_reusable(isolated_runner):
    sim_state, _, _ = _build_completed_sim(isolated_runner)
    ok, why = po.PipelineOrchestrator()._completed_sim_reusable(
        _pipeline_state(), sim_state)
    assert ok is True and why == ""


def test_knob_off_restores_legacy_rerun(isolated_runner, monkeypatch):
    sim_state, _, _ = _build_completed_sim(isolated_runner)
    monkeypatch.setenv("SIM_RESUME_REUSE_COMPLETED", "false")
    ok, why = po.PipelineOrchestrator()._completed_sim_reusable(
        _pipeline_state(), sim_state)
    assert ok is False and why == "sim_resume_reuse_completed_disabled"
    # Config 关闭（无 env）同样恢复 legacy。
    monkeypatch.delenv("SIM_RESUME_REUSE_COMPLETED", raising=False)
    monkeypatch.setattr(Config, "SIM_RESUME_REUSE_COMPLETED", False, raising=False)
    ok, _ = po.PipelineOrchestrator()._completed_sim_reusable(
        _pipeline_state(), sim_state)
    assert ok is False


def test_hollow_rc0_sim_is_not_reusable(isolated_runner):
    """DEFECT-2 组合：rc=0 但无 simulation_end 的 hollow 运行绝不复用。"""
    sim_state, _, _ = _build_completed_sim(
        isolated_runner, with_end=False,
        run_state_status="failed", run_state_completed=False)
    ok, why = po.PipelineOrchestrator()._completed_sim_reusable(
        _pipeline_state(), sim_state)
    assert ok is False
    assert why.startswith("missing_simulation_end:")
    assert "twitter" in why and "reddit" in why


def test_backend_restart_window_reuses_via_actions_marker(isolated_runner):
    """后端重启窗口：run_state 被孤儿回收成 FAILED / 停在 RUNNING（无存活进程），
    但 detached 子进程早已干净收尾（actions.jsonl 带 simulation_end）→ 仍可复用。"""
    for status in ("failed", "running"):
        SimulationRunner._run_states.clear()
        sim_state, _, _ = _build_completed_sim(
            isolated_runner, run_state_status=status, run_state_completed=False)
        ok, why = po.PipelineOrchestrator()._completed_sim_reusable(
            _pipeline_state(), sim_state)
        assert ok is True, f"status={status} why={why}"


def test_tampered_config_seal_forces_rerun(isolated_runner):
    sim_state, _, _ = _build_completed_sim(isolated_runner)
    cfg_path = os.path.join(isolated_runner, SIM_ID, "simulation_config.json")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["agent_configs"][0]["stance"] = "tampered"
    _write_json(cfg_path, cfg)
    ok, why = po.PipelineOrchestrator()._completed_sim_reusable(
        _pipeline_state(), sim_state)
    assert ok is False and why.startswith("config_seal_mismatch:")


def test_stale_prepared_fingerprint_forces_rerun(isolated_runner):
    """prepared state 指纹与磁盘 seal 不一致（PREPARE 已换代）→ 不复用。"""
    sim_state, _, _ = _build_completed_sim(isolated_runner)
    sim_state.simulation_config_manifest_sha256 = "0" * 64
    ok, why = po.PipelineOrchestrator()._completed_sim_reusable(
        _pipeline_state(), sim_state)
    assert ok is False and why.startswith("config_seal_mismatch:")


def test_missing_seal_identity_fails_closed(isolated_runner):
    """pre-seal 遗留（无 manifest、prepared state 无指纹）→ 无身份可核验，照旧重跑。"""
    sim_state, _, _ = _build_completed_sim(isolated_runner)
    os.remove(os.path.join(isolated_runner, SIM_ID, "simulation_config_manifest.json"))
    sim_state.simulation_config_sha256 = None
    sim_state.simulation_config_manifest_sha256 = None
    ok, why = po.PipelineOrchestrator()._completed_sim_reusable(
        _pipeline_state(), sim_state)
    assert ok is False and why == "no_config_seal_identity"


def test_half_written_run_summary_forces_rerun(isolated_runner):
    sim_state, _, _ = _build_completed_sim(isolated_runner)
    summary_path = os.path.join(isolated_runner, SIM_ID, "run_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write('{"simulation_id": "sim_reuse_fixture", "rounds_ex')  # 截断半写
    ok, why = po.PipelineOrchestrator()._completed_sim_reusable(
        _pipeline_state(), sim_state)
    assert ok is False and why == "run_summary_invalid"


def test_foreign_run_summary_identity_forces_rerun(isolated_runner):
    sim_state, _, _ = _build_completed_sim(isolated_runner)
    _write_json(os.path.join(isolated_runner, SIM_ID, "run_summary.json"),
                {"simulation_id": "sim_other", "rounds_executed": 3})
    ok, why = po.PipelineOrchestrator()._completed_sim_reusable(
        _pipeline_state(), sim_state)
    assert ok is False and why == "run_summary_identity_mismatch"


def test_missing_run_summary_still_reusable_for_backfill(isolated_runner):
    """summary 缺失（崩溃在聚合之前）：完整 actions.jsonl 可回填 → 允许复用；
    回填失败仍会被 DEFECT-2 完成证据门拦下（见下方 gate 测试）。"""
    sim_state, _, _ = _build_completed_sim(isolated_runner, with_summary=False)
    ok, why = po.PipelineOrchestrator()._completed_sim_reusable(
        _pipeline_state(), sim_state)
    assert ok is True, why


def test_runtime_attestation_seal_mismatch_forces_rerun(isolated_runner):
    """运行期见证（子进程启动时验证过的 seal SHA）与当前 seal 不一致 → 这场运行
    不属于当前密封配置，不复用。"""
    sim_state, _, _ = _build_completed_sim(isolated_runner)
    _write_json(
        os.path.join(isolated_runner, SIM_ID, "reddit_runtime_system_messages.json"),
        {"schema_version": "reddit-runtime-system-messages/v1",
         "simulation_config_manifest_sha256": "f" * 64})
    ok, why = po.PipelineOrchestrator()._completed_sim_reusable(
        _pipeline_state(), sim_state)
    assert ok is False and why == "runtime_attestation_seal_mismatch"


def test_identity_mismatch_and_missing_dir_fail_closed(isolated_runner):
    sim_state, _, _ = _build_completed_sim(isolated_runner)
    other = _pipeline_state()
    other.simulation_id = "sim_other"
    ok, why = po.PipelineOrchestrator()._completed_sim_reusable(other, sim_state)
    assert ok is False and why == "simulation_identity_mismatch"
    state = _pipeline_state()
    state.simulation_id = None
    ok, why = po.PipelineOrchestrator()._completed_sim_reusable(state, sim_state)
    assert ok is False and why == "no_simulation_identity"


def test_detection_never_relaunches_subprocess(isolated_runner, monkeypatch):
    """复用判定是只读探测：全程绝不触碰 start_simulation（stub/spy runner）。"""
    sim_state, _, _ = _build_completed_sim(isolated_runner)

    def _spy(*args, **kwargs):
        raise AssertionError("复用判定绝不允许重启模拟子进程")

    monkeypatch.setattr(SimulationRunner, "start_simulation", _spy)
    ok, why = po.PipelineOrchestrator()._completed_sim_reusable(
        _pipeline_state(), sim_state)
    assert ok is True, why


def test_live_running_sim_is_not_reused(isolated_runner, monkeypatch):
    """仍有存活进程在跑回合 → 半成品文件绝不当完成结果复用。"""
    sim_state, _, _ = _build_completed_sim(
        isolated_runner, run_state_status="running", run_state_completed=False)
    monkeypatch.setattr(SimulationRunner, "_is_simulation_alive",
                        classmethod(lambda cls, rs: True))
    ok, why = po.PipelineOrchestrator()._completed_sim_reusable(
        _pipeline_state(), sim_state)
    assert ok is False and why == "simulation_process_still_running"


# ------------------------------------------------- 完成标记探针（共用原语）
def test_simulation_end_probe_reads_tail_only(tmp_path):
    path = str(tmp_path / "actions.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for i in range(5000):
            f.write(json.dumps({"round": i, "action_type": "LIKE_POST",
                                "action_args": {"note": "x" * 80}}) + "\n")
        f.write(json.dumps({"event_type": "simulation_end",
                            "total_rounds": 18}) + "\n")
    assert po._actions_simulation_end_present(path) is True


def test_simulation_end_probe_rejects_lookalike_payloads(tmp_path):
    """动作正文里出现 'simulation_end' 字样不算完成证据；损坏行被容错跳过。"""
    path = str(tmp_path / "actions.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"action_type": "CREATE_POST",
                            "action_args": {"content": "simulation_end soon"}}) + "\n")
        f.write('{"event_type": "simulation_end", TRUNCATED\n')
    assert po._actions_simulation_end_present(path) is False
    assert po._actions_simulation_end_present(str(tmp_path / "missing.jsonl")) is False


# ------------------------------------------------- DEFECT-2: 完成证据门
def test_gate_raises_on_missing_completion_marker(isolated_runner):
    _build_completed_sim(isolated_runner, with_end=False,
                         run_state_status="failed", run_state_completed=False)
    rs = SimulationRunner.get_run_state(SIM_ID)
    with pytest.raises(RuntimeError) as ei:
        po.PipelineOrchestrator()._require_run_completion_evidence(
            _pipeline_state(), SIM_ID, rs, True)
    msg = str(ei.value)
    assert "simulation_end" in msg and "退出码不是完成证据" in msg


def test_gate_raises_on_invalid_run_summary(isolated_runner):
    sim_state, _, _ = _build_completed_sim(isolated_runner)
    rs = SimulationRunner.get_run_state(SIM_ID)
    with pytest.raises(RuntimeError, match="run_summary.json"):
        po.PipelineOrchestrator()._require_run_completion_evidence(
            _pipeline_state(), SIM_ID, rs, False)


def test_gate_passes_with_full_evidence(isolated_runner):
    _build_completed_sim(isolated_runner)
    rs = SimulationRunner.get_run_state(SIM_ID)
    po.PipelineOrchestrator()._require_run_completion_evidence(
        _pipeline_state(), SIM_ID, rs, True)  # 不抛 = 放行


def test_gate_accepts_actions_marker_when_run_state_stale(isolated_runner):
    """复用路径：run_state 位过期（False）但 actions.jsonl 已有 simulation_end。"""
    _build_completed_sim(isolated_runner, run_state_status="failed",
                         run_state_completed=False)
    rs = SimulationRunner.get_run_state(SIM_ID)
    po.PipelineOrchestrator()._require_run_completion_evidence(
        _pipeline_state(), SIM_ID, rs, True)


def test_gate_fails_closed_without_any_platform_evidence(isolated_runner, tmp_path):
    with pytest.raises(RuntimeError, match="simulation_end"):
        po.PipelineOrchestrator()._require_run_completion_evidence(
            _pipeline_state(), "sim_never_ran", None, True)


# ------------------------------------------------- _run 接线特征化（getsource）
def test_run_stage_wiring_characterization():
    """接线契约（与 test_foglamp_containment 的 getsource 先例同构）：

    (1) DEFECT-1 探测（_completed_sim_reusable → _sim_disk_reuse）发生在
        start_simulation 之前，且折入 run_stage_done（复用分支不重启子进程）；
    (2) DEFECT-2 完成证据门（_require_run_completion_evidence）站在
        _complete_stage(STAGE_RUN) 之前；
    (3) DEFECT-3 计量（_record_sim_run_telemetry）同时接在成功边界（_complete_stage
        之前）与失败边界（except BaseException 后 re-raise 之前）。
    """
    src = inspect.getsource(po.PipelineOrchestrator._run)
    i_detect = src.index("_completed_sim_reusable(state, sim_state)")
    i_launch = src.index(
        "SimulationRunner.start_simulation(simulation_id=sim_state.simulation_id")
    i_fold = src.index('state.options["resumed_stage_validation"] = '
                       '"run_reused_completed_simulation"')
    i_gate = src.index("_require_run_completion_evidence(")
    i_meter = src.index("self._record_sim_run_telemetry(state, sim_state.simulation_id)")
    import re
    completion = re.search(r"STAGE_RUN,\s+_run_completion_message", src)
    assert completion is not None, "Legacy RUN completion must remain wired"
    i_complete = completion.start()
    assert i_detect < i_launch, "探测必须先于子进程重启决策"
    assert i_fold < i_launch, "复用折叠必须先于 start_simulation 分支"
    assert i_gate < i_complete, "完成证据门必须先于 RUN 阶段 seal"
    assert i_meter < i_complete or src.count(
        "self._record_sim_run_telemetry(state, sim_state.simulation_id)") >= 2
    # 失败边界：except BaseException → 记账 → raise（不吞异常）。
    i_exc = src.index("except BaseException:")
    tail = src[i_exc:i_exc + 700]
    assert "_record_sim_run_telemetry" in tail and "raise" in tail
    # 成功边界：记账在完成证据门之前（门若判失败也不丢已烧掉的 token 账）、
    # 且在 _complete_stage(STAGE_RUN) 之前。
    i_success_meter = src.rindex(
        "self._record_sim_run_telemetry(state, sim_state.simulation_id)")
    assert i_success_meter < i_gate < i_complete
