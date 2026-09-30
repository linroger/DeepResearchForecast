"""Audit fixes — runner group (RUN-7/11/12/13/15/16/17, XRUN-2/4/9, RUN-18).

Offline: no LLM/network. run_parallel_simulation imports oasis/camel from the
venv but only pure / filesystem helpers are exercised here.
"""

import json
import os
import sqlite3
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_BACKEND, "scripts")
for _p in (_BACKEND, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_parallel_simulation as rps  # noqa: E402
from app.config import Config  # noqa: E402
from app.services.simulation_runner import (  # noqa: E402
    RunnerStatus,
    SimulationRunner,
    SimulationRunState,
)
from app.utils import oasis_llm  # noqa: E402


@pytest.fixture
def sim_env(tmp_path, monkeypatch):
    """Isolated RUN_STATE_DIR + clean in-memory runner registries."""
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationRunner, "_run_states", {})
    monkeypatch.setattr(SimulationRunner, "_run_state_last_save", {})
    monkeypatch.setattr(SimulationRunner, "_processes", {})
    monkeypatch.setattr(SimulationRunner, "_action_queues", {})
    monkeypatch.setattr(SimulationRunner, "_stdout_files", {})
    monkeypatch.setattr(SimulationRunner, "_stderr_files", {})
    monkeypatch.setattr(SimulationRunner, "_graph_memory_enabled", {})
    monkeypatch.setattr(SimulationRunner, "_cleanup_done", False)
    return tmp_path


def _write_actions(sim_dir, platform, entries):
    plat_dir = os.path.join(str(sim_dir), platform)
    os.makedirs(plat_dir, exist_ok=True)
    with open(os.path.join(plat_dir, "actions.jsonl"), "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- RUN-11
def test_mark_env_stopped_overwrites_alive(sim_env):
    sim_id = "sim_run11"
    sim_dir = sim_env / sim_id
    sim_dir.mkdir()
    (sim_dir / "env_status.json").write_text(
        json.dumps({"status": "alive", "twitter_available": True}), encoding="utf-8")
    assert SimulationRunner.check_env_alive(sim_id) is True

    SimulationRunner._mark_env_stopped(sim_id)
    assert SimulationRunner.check_env_alive(sim_id) is False
    detail = SimulationRunner.get_env_status_detail(sim_id)
    assert detail["status"] == "stopped"
    assert detail["twitter_available"] is False


def test_mark_env_stopped_missing_dir_noop(sim_env):
    # 目录不存在时不得创建游离文件、不得抛出
    SimulationRunner._mark_env_stopped("sim_never_ran")
    assert not (sim_env / "sim_never_ran").exists()


def test_stop_simulation_marks_env_stopped(sim_env):
    sim_id = "sim_run11_stop"
    state = SimulationRunState(simulation_id=sim_id, runner_status=RunnerStatus.RUNNING)
    SimulationRunner._save_run_state(state)
    (sim_env / sim_id / "env_status.json").write_text(
        json.dumps({"status": "alive"}), encoding="utf-8")

    out = SimulationRunner.stop_simulation(sim_id)  # 无 pid/进程 → 视为已终止
    assert out.runner_status == RunnerStatus.STOPPED
    assert SimulationRunner.check_env_alive(sim_id) is False


# ---------------------------------------------------------------- RUN-16
def test_stop_simulation_allows_starting(sim_env):
    sim_id = "sim_run16"
    state = SimulationRunState(simulation_id=sim_id, runner_status=RunnerStatus.STARTING)
    SimulationRunner._save_run_state(state)
    out = SimulationRunner.stop_simulation(sim_id)
    assert out.runner_status == RunnerStatus.STOPPED


def test_stop_simulation_still_rejects_completed(sim_env):
    sim_id = "sim_run16_completed"
    state = SimulationRunState(simulation_id=sim_id, runner_status=RunnerStatus.COMPLETED)
    SimulationRunner._save_run_state(state)
    with pytest.raises(ValueError):
        SimulationRunner.stop_simulation(sim_id)


# ---------------------------------------------------------------- RUN-12
def test_interview_timeout_scales_with_batch(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude-cli")
    monkeypatch.delenv("OASIS_CLI_SEMAPHORE", raising=False)
    monkeypatch.setattr(Config, "INTERVIEW_TIMEOUT_PER_AGENT", 30.0, raising=False)
    # 80 采访 / 并发 4 → 60 + 30*20 = 660s（远大于旧的 180s 全场超时）
    assert SimulationRunner._scale_interview_timeout(180.0, 80) == 660.0


def test_interview_timeout_never_shrinks(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude-cli")
    monkeypatch.delenv("OASIS_CLI_SEMAPHORE", raising=False)
    monkeypatch.setattr(Config, "INTERVIEW_TIMEOUT_PER_AGENT", 30.0, raising=False)
    # 单个采访：60+30=90 < 传入 120 → 保留调用方超时
    assert SimulationRunner._scale_interview_timeout(120.0, 1) == 120.0


def test_interview_timeout_scaling_disabled(monkeypatch):
    monkeypatch.setattr(Config, "INTERVIEW_TIMEOUT_PER_AGENT", 0, raising=False)
    assert SimulationRunner._scale_interview_timeout(180.0, 80) == 180.0


# ---------------------------------------------------------------- XRUN-9
def test_timeline_first_last_not_inverted(sim_env):
    sim_id = "sim_xrun9"
    _write_actions(sim_env / sim_id, "twitter", [
        {"round": 1, "timestamp": "2026-07-02T03:55:47", "agent_id": 1,
         "agent_name": "A", "action_type": "CREATE_POST", "action_args": {}},
        {"round": 1, "timestamp": "2026-07-02T03:53:05", "agent_id": 2,
         "agent_name": "B", "action_type": "LIKE_POST", "action_args": {}},
    ])
    timeline = SimulationRunner.get_timeline(sim_id)
    assert len(timeline) == 1
    r = timeline[0]
    assert r["first_action_time"] == "2026-07-02T03:53:05"
    assert r["last_action_time"] == "2026-07-02T03:55:47"
    assert r["first_action_time"] <= r["last_action_time"]


def test_agent_stats_first_last_not_inverted(sim_env):
    sim_id = "sim_xrun9_agent"
    _write_actions(sim_env / sim_id, "twitter", [
        {"round": 2, "timestamp": "2026-07-02T05:00:00", "agent_id": 7,
         "agent_name": "N", "action_type": "CREATE_POST", "action_args": {}},
        {"round": 1, "timestamp": "2026-07-02T04:00:00", "agent_id": 7,
         "agent_name": "N", "action_type": "LIKE_POST", "action_args": {}},
    ])
    stats = SimulationRunner.get_agent_stats(sim_id)
    assert stats[0]["first_action_time"] == "2026-07-02T04:00:00"
    assert stats[0]["last_action_time"] == "2026-07-02T05:00:00"


# ------------------------------------------------- SIM-5 organic vs injected per agent
def test_agent_stats_split_organic_and_injected_actions(sim_env):
    sim_id = "sim_sim5_stats"
    _write_actions(sim_env / sim_id, "twitter", [
        # agent 0: the top-influence fallback poster — timeline replays only
        {"round": 1, "timestamp": "2026-07-02T01:00:00", "agent_id": 0, "agent_name": "Top",
         "action_type": "CREATE_POST", "action_args": {"content": "e1", "is_scheduled_event": True}},
        {"round": 2, "timestamp": "2026-07-02T02:00:00", "agent_id": 0, "agent_name": "Top",
         "action_type": "CREATE_POST", "action_args": {"content": "e2", "is_scheduled_event": True}},
        {"round": 3, "timestamp": "2026-07-02T03:00:00", "agent_id": 0, "agent_name": "Top",
         "action_type": "CREATE_POST", "action_args": {"content": "e3", "is_scheduled_event": True}},
        # agent 1: a round-0 seed post, a seed follow, a sampled like, one organic comment
        {"round": 0, "timestamp": "2026-07-02T00:00:01", "agent_id": 1, "agent_name": "Org",
         "action_type": "CREATE_POST", "action_args": {"content": "seed"}},
        {"round": 1, "timestamp": "2026-07-02T01:00:01", "agent_id": 1, "agent_name": "Org",
         "action_type": "FOLLOW", "action_args": {"is_seed_action": True}},
        {"round": 2, "timestamp": "2026-07-02T02:00:01", "agent_id": 1, "agent_name": "Org",
         "action_type": "LIKE_POST", "action_args": {"post_id": 1, "is_engagement_sample": True}},
        {"round": 2, "timestamp": "2026-07-02T02:00:02", "agent_id": 1, "agent_name": "Org",
         "action_type": "CREATE_COMMENT", "action_args": {"content": "reply", "post_id": 1}},
        # agent 2: organic only
        {"round": 1, "timestamp": "2026-07-02T01:00:02", "agent_id": 2, "agent_name": "Solo",
         "action_type": "CREATE_POST", "action_args": {"content": "own"}},
    ])
    stats = SimulationRunner.get_agent_stats(sim_id)
    by_id = {s["agent_id"]: s for s in stats}
    # sort order is still total_actions (API compatibility)
    assert [s["agent_id"] for s in stats] == [1, 0, 2]
    assert (by_id[0]["organic_actions"], by_id[0]["injected_actions"]) == (0, 3)
    assert by_id[0]["organic_action_types"] == {}
    assert (by_id[1]["organic_actions"], by_id[1]["injected_actions"]) == (1, 3)
    assert by_id[1]["organic_action_types"] == {"CREATE_COMMENT": 1}
    assert by_id[1]["action_types"] == {"CREATE_COMMENT": 1, "LIKE_POST": 1, "FOLLOW": 1,
                                        "CREATE_POST": 1}
    assert (by_id[2]["organic_actions"], by_id[2]["injected_actions"]) == (1, 0)
    assert all(s["organic_actions"] + s["injected_actions"] == s["total_actions"] for s in stats)


def test_agent_stats_provenance_off_keeps_legacy_fields(sim_env, monkeypatch):
    monkeypatch.setattr(Config, "SIM_EVENT_PROVENANCE", False)
    sim_id = "sim_sim5_stats_off"
    _write_actions(sim_env / sim_id, "twitter", [
        {"round": 1, "timestamp": "2026-07-02T01:00:00", "agent_id": 0, "agent_name": "Top",
         "action_type": "CREATE_POST", "action_args": {"content": "e1", "is_scheduled_event": True}},
    ])
    stats = SimulationRunner.get_agent_stats(sim_id)
    assert set(stats[0]) == {"agent_id", "agent_name", "total_actions", "twitter_actions",
                             "reddit_actions", "action_types", "first_action_time",
                             "last_action_time"}


# ------------------------------------------------- RUN-13 / XRUN-2(2)
def test_run_summary_excludes_seeds_and_scheduled_from_organic(sim_env):
    sim_id = "sim_run13"
    _write_actions(sim_env / sim_id, "twitter", [
        # round-0 种子帖 + 种子 FOLLOW —— 不是 agent 决策
        {"round": 0, "timestamp": "2026-07-02T00:00:01", "agent_id": 0,
         "agent_name": "Seed", "action_type": "CREATE_POST",
         "action_args": {"content": "seed post"}},
        {"round": 0, "timestamp": "2026-07-02T00:00:02", "agent_id": 1,
         "agent_name": "F", "action_type": "FOLLOW",
         "action_args": {"is_seed_action": True}},
        # 时间线回放事件 —— 注入而非 agent 决策
        {"round": 3, "timestamp": "2026-07-02T00:03:00", "agent_id": 0,
         "agent_name": "Seed", "action_type": "CREATE_POST",
         "action_args": {"content": "scheduled", "is_scheduled_event": True}},
        # 真正的有机动作
        {"round": 2, "timestamp": "2026-07-02T00:02:00", "agent_id": 5,
         "agent_name": "Org", "action_type": "CREATE_POST",
         "action_args": {"content": "organic post"}},
        {"round": 4, "timestamp": "2026-07-02T00:04:00", "agent_id": 6,
         "agent_name": "L", "action_type": "LIKE_POST", "action_args": {}},
    ])
    summary = SimulationRunner.write_run_summary(sim_id)
    assert summary is not None
    assert summary["organic_action_count"] == 2
    assert summary["rounds_with_organic_actions"] == 2
    # top_posts: 只含有机帖，按轮次升序，且不再混入种子/回放
    contents = [p["content"] for p in summary["top_posts"]]
    assert contents == ["organic post"]
    assert summary["simulation_health"] != "hollow"


def test_run_summary_seed_only_run_is_hollow(sim_env):
    sim_id = "sim_run13_hollow"
    _write_actions(sim_env / sim_id, "twitter", [
        {"round": 0, "timestamp": "2026-07-02T00:00:01", "agent_id": 0,
         "agent_name": "Seed", "action_type": "CREATE_POST",
         "action_args": {"content": "seed"}},
        {"round": 1, "timestamp": "2026-07-02T00:01:00", "agent_id": 1,
         "agent_name": "F", "action_type": "FOLLOW", "action_args": {}},
    ])
    summary = SimulationRunner.write_run_summary(sim_id)
    assert summary["organic_action_count"] == 0
    assert summary["simulation_health"] == "hollow"
    assert summary["top_posts"] == []


# ---------------------------------------------------------------- ITEM 20 (4) simulated_hours
def _write_run_state(sim_dir, current_round, total_rounds):
    os.makedirs(str(sim_dir), exist_ok=True)
    with open(os.path.join(str(sim_dir), "run_state.json"), "w", encoding="utf-8") as f:
        json.dump({"current_round": current_round, "total_rounds": total_rounds}, f)


def _write_sim_config(sim_dir, minutes_per_round):
    os.makedirs(str(sim_dir), exist_ok=True)
    with open(os.path.join(str(sim_dir), "simulation_config.json"), "w", encoding="utf-8") as f:
        json.dump({"time_config": {"minutes_per_round": minutes_per_round}}, f)


def test_run_summary_simulated_hours_from_rounds(sim_env):
    """ITEM20(4): simulated_hours = rounds_executed × minutes_per_round / 60（历史上恒 0）。"""
    sim_id = "sim_item20_hours"
    _write_actions(sim_env / sim_id, "twitter", [
        {"round": 1, "timestamp": "2026-07-02T00:01:00", "agent_id": 5,
         "agent_name": "O", "action_type": "CREATE_POST", "action_args": {"content": "p"}},
    ])
    _write_run_state(sim_env / sim_id, current_round=12, total_rounds=24)
    _write_sim_config(sim_env / sim_id, minutes_per_round=30)
    summary = SimulationRunner.write_run_summary(sim_id)
    assert summary["rounds_executed"] == 12
    assert summary["simulated_hours"] == 6.0    # 12 × 30 / 60


def test_run_summary_simulated_hours_defaults_minutes_60(sim_env):
    """无 simulation_config.json → minutes_per_round 缺省 60（degrade-safe）。"""
    sim_id = "sim_item20_hours_default"
    _write_actions(sim_env / sim_id, "twitter", [
        {"round": 1, "timestamp": "2026-07-02T00:01:00", "agent_id": 5,
         "agent_name": "O", "action_type": "CREATE_POST", "action_args": {"content": "p"}},
    ])
    _write_run_state(sim_env / sim_id, current_round=3, total_rounds=10)
    summary = SimulationRunner.write_run_summary(sim_id)
    assert summary["simulated_hours"] == 3.0    # 3 × 60 / 60


# ---------------------------------------------------------------- ITEM 20 (2) ratio detector
def test_run_summary_flags_organic_ratio_collapse(sim_env, monkeypatch):
    """ITEM20(2): 连续 ≥K 轮 posts>0 而 comments+likes==0 → organic_ratio_warnings。"""
    monkeypatch.setattr(Config, "SIM_ORGANIC_RATIO_DETECTOR", True, raising=False)
    monkeypatch.setattr(Config, "SIM_ORGANIC_RATIO_MIN_CONSECUTIVE", 3, raising=False)
    sim_id = "sim_item20_collapse"
    entries = []
    for rnd in (1, 2, 3):        # 三连轮只发帖、零评论/点赞
        entries.append({"round": rnd, "timestamp": f"2026-07-02T00:0{rnd}:00",
                        "agent_id": rnd, "agent_name": f"A{rnd}",
                        "action_type": "CREATE_POST", "action_args": {"content": "x"}})
    _write_actions(sim_env / sim_id, "twitter", entries)
    _write_run_state(sim_env / sim_id, current_round=3, total_rounds=3)
    summary = SimulationRunner.write_run_summary(sim_id)
    warns = summary.get("organic_ratio_warnings")
    assert warns and warns[0]["platform"] == "twitter"
    assert warns[0]["rounds"] == 3


def test_run_summary_engagement_sample_likes_excluded_from_ratio(sim_env, monkeypatch):
    """ITEM20 诚实性交叉验证：is_engagement_sample 采样赞不得掩盖 agent 零点赞塌缩。"""
    monkeypatch.setattr(Config, "SIM_ORGANIC_RATIO_DETECTOR", True, raising=False)
    monkeypatch.setattr(Config, "SIM_ORGANIC_RATIO_MIN_CONSECUTIVE", 3, raising=False)
    sim_id = "sim_item20_sample_excluded"
    entries = []
    for rnd in (1, 2, 3):
        entries.append({"round": rnd, "timestamp": f"2026-07-02T00:0{rnd}:00",
                        "agent_id": rnd, "agent_name": f"A{rnd}",
                        "action_type": "CREATE_POST", "action_args": {"content": "x"}})
        # 采样赞（is_engagement_sample）——应被侦测器排除，仍判定为塌缩
        entries.append({"round": rnd, "timestamp": f"2026-07-02T00:0{rnd}:30",
                        "agent_id": 100 + rnd, "agent_name": f"S{rnd}",
                        "action_type": "LIKE_POST",
                        "action_args": {"post_id": rnd, "is_engagement_sample": True}})
    _write_actions(sim_env / sim_id, "twitter", entries)
    _write_run_state(sim_env / sim_id, current_round=3, total_rounds=3)
    summary = SimulationRunner.write_run_summary(sim_id)
    warns = summary.get("organic_ratio_warnings")
    assert warns and warns[0]["rounds"] == 3     # 采样赞未粉饰塌缩


def test_run_summary_ratio_detector_disabled(sim_env, monkeypatch):
    """SIM_ORGANIC_RATIO_DETECTOR=False → 不写 organic_ratio_warnings（关闭即 no-op）。"""
    monkeypatch.setattr(Config, "SIM_ORGANIC_RATIO_DETECTOR", False, raising=False)
    sim_id = "sim_item20_detector_off"
    entries = [{"round": rnd, "timestamp": f"2026-07-02T00:0{rnd}:00", "agent_id": rnd,
                "agent_name": f"A{rnd}", "action_type": "CREATE_POST",
                "action_args": {"content": "x"}} for rnd in (1, 2, 3)]
    _write_actions(sim_env / sim_id, "twitter", entries)
    _write_run_state(sim_env / sim_id, current_round=3, total_rounds=3)
    summary = SimulationRunner.write_run_summary(sim_id)
    assert "organic_ratio_warnings" not in summary


# ---------------------------------------------------------------- RUN-15
def test_rotate_stale_logs_rotates_derived_artifacts(sim_env):
    sim_id = "sim_run15"
    sim_dir = sim_env / sim_id
    (sim_dir / "twitter").mkdir(parents=True)
    (sim_dir / "twitter" / "actions.jsonl").write_text("{}\n", encoding="utf-8")
    (sim_dir / "twitter" / "checkpoint.json").write_text("{}", encoding="utf-8")
    (sim_dir / "run_summary.json").write_text("{}", encoding="utf-8")
    (sim_dir / "world_state_trajectory.json").write_text("{}", encoding="utf-8")
    (sim_dir / "decisions.jsonl").write_text("{}\n", encoding="utf-8")

    SimulationRunner._rotate_stale_action_logs(str(sim_dir))

    assert not (sim_dir / "run_summary.json").exists()
    assert (sim_dir / "run_summary.json.prev").exists()
    assert not (sim_dir / "world_state_trajectory.json").exists()
    assert (sim_dir / "world_state_trajectory.json.prev").exists()
    assert not (sim_dir / "twitter" / "actions.jsonl").exists()
    assert (sim_dir / "twitter" / "actions.prev.jsonl").exists()
    assert (sim_dir / "twitter" / "checkpoint.prev.json").exists()


def test_cleanup_simulation_logs_removes_derived_artifacts(sim_env):
    sim_id = "sim_run15_cleanup"
    sim_dir = sim_env / sim_id
    (sim_dir / "reddit").mkdir(parents=True)
    (sim_dir / "run_summary.json").write_text("{}", encoding="utf-8")
    (sim_dir / "run_summary.json.prev").write_text("{}", encoding="utf-8")
    (sim_dir / "llm_health.json").write_text("{}", encoding="utf-8")
    (sim_dir / "reddit" / "checkpoint.json").write_text("{}", encoding="utf-8")

    result = SimulationRunner.cleanup_simulation_logs(sim_id)
    assert result["success"] is True
    assert not (sim_dir / "run_summary.json").exists()
    assert not (sim_dir / "run_summary.json.prev").exists()
    assert not (sim_dir / "llm_health.json").exists()
    assert not (sim_dir / "reddit" / "checkpoint.json").exists()


# ---------------------------------------------------------------- RUN-17
class _DummyProc:
    pid = 424242

    def __init__(self, returncode=0):
        self.returncode = returncode

    def poll(self):
        return self.returncode


def test_action_log_publishes_completion_after_all_platform_evidence(sim_env):
    sim_id = "sim_run17_evidence"
    sim_dir = sim_env / sim_id
    state = SimulationRunState(
        simulation_id=sim_id,
        runner_status=RunnerStatus.RUNNING,
        twitter_enabled=True,
        reddit_enabled=True,
    )
    SimulationRunner._save_run_state(state)
    _write_actions(sim_dir, "twitter", [
        {"event_type": "simulation_end", "total_rounds": 2, "total_actions": 3},
    ])
    _write_actions(sim_dir, "reddit", [
        {"event_type": "simulation_end", "total_rounds": 2, "total_actions": 4},
    ])

    SimulationRunner._read_action_log(
        str(sim_dir / "twitter" / "actions.jsonl"), 0, state, "twitter")
    SimulationRunner._read_action_log(
        str(sim_dir / "reddit" / "actions.jsonl"), 0, state, "reddit")

    assert state.twitter_completed is True
    assert state.reddit_completed is True
    assert state.runner_status == RunnerStatus.COMPLETED
    assert state.completed_at is not None


def test_final_completion_event_during_stop_converges_to_stopped(sim_env):
    """A final buffered event may be recorded after stop intent, but cannot cancel the stop."""
    sim_id = "sim_run17_final_event_during_stop"
    sim_dir = sim_env / sim_id
    state = SimulationRunState(
        simulation_id=sim_id,
        runner_status=RunnerStatus.STOPPING,
        twitter_enabled=True,
        twitter_running=True,
    )
    SimulationRunner._save_run_state(state)
    _write_actions(sim_dir, "twitter", [
        {"event_type": "simulation_end", "total_rounds": 2, "total_actions": 3},
    ])
    SimulationRunner._processes[sim_id] = _DummyProc(returncode=0)

    SimulationRunner._monitor_simulation(sim_id)

    final = SimulationRunner.get_run_state(sim_id)
    assert final.twitter_completed is True
    assert final.runner_status == RunnerStatus.STOPPED
    assert final.completed_at is not None


def test_final_completion_event_cannot_overwrite_failed_result(sim_env):
    """Late log flushes preserve failure truth and its diagnostic details."""
    sim_id = "sim_run17_final_event_after_failure"
    sim_dir = sim_env / sim_id
    state = SimulationRunState(
        simulation_id=sim_id,
        runner_status=RunnerStatus.FAILED,
        twitter_enabled=True,
        error="provider failed before shutdown",
    )
    SimulationRunner._save_run_state(state)
    _write_actions(sim_dir, "twitter", [
        {"event_type": "simulation_end", "total_rounds": 2, "total_actions": 3},
    ])
    SimulationRunner._processes[sim_id] = _DummyProc(returncode=0)

    SimulationRunner._monitor_simulation(sim_id)

    final = SimulationRunner.get_run_state(sim_id)
    assert final.twitter_completed is True
    assert final.runner_status == RunnerStatus.FAILED
    assert final.error == "provider failed before shutdown"


def test_monitor_rejects_exit_zero_without_all_platform_completion(sim_env):
    sim_id = "sim_run17"
    state = SimulationRunState(
        simulation_id=sim_id,
        runner_status=RunnerStatus.RUNNING,
        twitter_enabled=True,
        reddit_enabled=True,
        twitter_completed=True,
        reddit_completed=False,  # Reddit 从未发出 simulation_end
    )
    SimulationRunner._save_run_state(state)
    (sim_env / sim_id / "simulation.log").write_text(
        "磁盘预检失败，拒绝启动模拟: 可用磁盘 1.61 GB 低于阈值 2.0 GB\n",
        encoding="utf-8",
    )
    SimulationRunner._processes[sim_id] = _DummyProc()

    SimulationRunner._monitor_simulation(sim_id)

    final = SimulationRunner.get_run_state(sim_id)
    assert final.runner_status == RunnerStatus.FAILED
    assert final.error and "simulation_end" in final.error
    assert "磁盘预检失败" in final.error
    assert final.completed_at is None
    # RUN-11: 进程退出后环境必须标记 stopped
    assert SimulationRunner.check_env_alive(sim_id) is False


def test_monitor_no_error_when_all_platforms_completed(sim_env):
    sim_id = "sim_run17_ok"
    state = SimulationRunState(
        simulation_id=sim_id,
        runner_status=RunnerStatus.RUNNING,
        twitter_enabled=True,
        reddit_enabled=False,
        twitter_completed=True,
    )
    SimulationRunner._save_run_state(state)
    SimulationRunner._processes[sim_id] = _DummyProc()

    SimulationRunner._monitor_simulation(sim_id)

    final = SimulationRunner.get_run_state(sim_id)
    assert final.runner_status == RunnerStatus.COMPLETED
    assert final.error is None


def test_monitor_completes_valid_dual_platform_exit_zero(sim_env):
    sim_id = "sim_run17_dual_ok"
    state = SimulationRunState(
        simulation_id=sim_id,
        runner_status=RunnerStatus.RUNNING,
        twitter_enabled=True,
        reddit_enabled=True,
        twitter_completed=True,
        reddit_completed=True,
    )
    SimulationRunner._save_run_state(state)
    SimulationRunner._processes[sim_id] = _DummyProc(returncode=0)

    SimulationRunner._monitor_simulation(sim_id)

    final = SimulationRunner.get_run_state(sim_id)
    assert final.runner_status == RunnerStatus.COMPLETED
    assert final.completed_at is not None
    assert final.error is None


def test_monitor_nonzero_exit_is_failed_without_completion_timestamp(sim_env):
    sim_id = "sim_run17_nonzero_incomplete"
    state = SimulationRunState(
        simulation_id=sim_id,
        runner_status=RunnerStatus.RUNNING,
        twitter_enabled=True,
        reddit_enabled=True,
        twitter_completed=False,
        reddit_completed=False,
    )
    SimulationRunner._save_run_state(state)
    SimulationRunner._processes[sim_id] = _DummyProc(returncode=7)

    SimulationRunner._monitor_simulation(sim_id)

    final = SimulationRunner.get_run_state(sim_id)
    assert final.runner_status == RunnerStatus.FAILED
    assert final.completed_at is None
    assert final.error and "退出码: 7" in final.error


def test_monitor_preserves_completed_result_when_command_process_exits_nonzero(sim_env):
    """Post-result command-mode failure affects interviews, not the completed simulation result."""
    sim_id = "sim_run17_nonzero_after_completion"
    completed_at = "2026-07-10T12:00:00"
    state = SimulationRunState(
        simulation_id=sim_id,
        runner_status=RunnerStatus.COMPLETED,
        twitter_enabled=True,
        reddit_enabled=True,
        twitter_completed=True,
        reddit_completed=True,
        completed_at=completed_at,
    )
    SimulationRunner._save_run_state(state)
    SimulationRunner._processes[sim_id] = _DummyProc(returncode=7)

    SimulationRunner._monitor_simulation(sim_id)

    final = SimulationRunner.get_run_state(sim_id)
    assert final.runner_status == RunnerStatus.COMPLETED
    assert final.completed_at == completed_at
    assert final.error is None


def test_read_log_tail_is_bounded_and_keeps_last_failure(sim_env):
    path = sim_env / "large.log"
    path.write_bytes((b"x" * 100_000) + "\n磁盘预检失败\n".encode("utf-8"))

    tail = SimulationRunner._read_log_tail(str(path), max_bytes=256)

    assert "磁盘预检失败" in tail
    assert len(tail.encode("utf-8")) <= 260  # mid-codepoint replacement may add a few bytes


# -------------------------------------------------------------- LOOP-002
def _install_cleanup_spies(monkeypatch):
    calls = {"terminated": [], "synced": [], "env_stopped": []}

    def fake_terminate(cls, process, simulation_id, timeout=10):
        calls["terminated"].append((simulation_id, timeout))
        process.returncode = -15

    def fake_sync(cls, simulation_id, status):
        calls["synced"].append((simulation_id, status))

    def fake_mark_env_stopped(cls, simulation_id):
        calls["env_stopped"].append(simulation_id)

    monkeypatch.setattr(
        SimulationRunner, "_terminate_process", classmethod(fake_terminate))
    monkeypatch.setattr(
        SimulationRunner, "_sync_state_json_status", classmethod(fake_sync))
    monkeypatch.setattr(
        SimulationRunner, "_mark_env_stopped", classmethod(fake_mark_env_stopped))
    return calls


def _replay_monitor_after_cleanup(simulation_id, process):
    """Replay the production ordering where the monitor observes cleanup's process exit last."""
    SimulationRunner._processes[simulation_id] = process
    SimulationRunner._monitor_simulation(simulation_id)


def test_shutdown_cleanup_preserves_completed_simulation_result(sim_env, monkeypatch):
    """Killing the post-simulation interview process must not erase completion truth."""
    sim_id = "sim_loop002_completed"
    completed_at = "2026-07-10T12:00:00"
    state = SimulationRunState(
        simulation_id=sim_id,
        runner_status=RunnerStatus.COMPLETED,
        twitter_enabled=True,
        twitter_completed=True,
        completed_at=completed_at,
    )
    SimulationRunner._save_run_state(state)
    process = _DummyProc(returncode=None)
    SimulationRunner._processes[sim_id] = process
    calls = _install_cleanup_spies(monkeypatch)

    SimulationRunner.cleanup_all_simulations()
    _replay_monitor_after_cleanup(sim_id, process)

    final = SimulationRunner.get_run_state(sim_id)
    assert final.runner_status == RunnerStatus.COMPLETED
    assert final.completed_at == completed_at
    assert final.error is None
    assert calls["terminated"] == [(sim_id, 5)]
    assert calls["synced"] == [(sim_id, "completed")]
    assert calls["env_stopped"] == [sim_id, sim_id]


def test_shutdown_cleanup_preserves_failed_simulation_result(sim_env, monkeypatch):
    """Cleanup must not hide an existing failure behind a later stopped status."""
    sim_id = "sim_loop002_failed"
    state = SimulationRunState(
        simulation_id=sim_id,
        runner_status=RunnerStatus.FAILED,
        twitter_enabled=True,
        twitter_running=True,
        error="provider failed during simulation",
    )
    SimulationRunner._save_run_state(state)
    process = _DummyProc(returncode=None)
    SimulationRunner._processes[sim_id] = process
    calls = _install_cleanup_spies(monkeypatch)

    SimulationRunner.cleanup_all_simulations()
    _replay_monitor_after_cleanup(sim_id, process)

    final = SimulationRunner.get_run_state(sim_id)
    assert final.runner_status == RunnerStatus.FAILED
    assert final.completed_at is None
    assert final.error == "provider failed during simulation"
    assert final.twitter_running is False
    assert calls["synced"] == [(sim_id, "failed")]
    assert calls["env_stopped"] == [sim_id, sim_id]


def test_shutdown_cleanup_marks_active_simulation_stopped(sim_env, monkeypatch):
    """Cleanup still records a truthful operator stop for an unfinished simulation."""
    sim_id = "sim_loop002_running"
    state = SimulationRunState(
        simulation_id=sim_id,
        runner_status=RunnerStatus.RUNNING,
        twitter_enabled=True,
        twitter_running=True,
    )
    SimulationRunner._save_run_state(state)
    process = _DummyProc(returncode=None)
    SimulationRunner._processes[sim_id] = process
    calls = _install_cleanup_spies(monkeypatch)

    SimulationRunner.cleanup_all_simulations()
    _replay_monitor_after_cleanup(sim_id, process)

    final = SimulationRunner.get_run_state(sim_id)
    assert final.runner_status == RunnerStatus.STOPPED
    assert final.completed_at is not None
    assert final.error == "服务器关闭，模拟被终止"
    assert final.twitter_running is False
    assert calls["terminated"] == [(sim_id, 5)]
    assert calls["synced"] == [(sim_id, "stopped")]
    assert calls["env_stopped"] == [sim_id, sim_id]


# ---------------------------------------------------------------- RUN-7 (runner side)
def test_resume_checkpoint_round_reads_max_platform_round(sim_env):
    sim_dir = sim_env / "sim_run7"
    (sim_dir / "twitter").mkdir(parents=True)
    (sim_dir / "reddit").mkdir(parents=True)
    (sim_dir / "twitter" / "checkpoint.json").write_text(
        json.dumps({"completed_round": 7}), encoding="utf-8")
    (sim_dir / "reddit" / "checkpoint.json").write_text(
        json.dumps({"completed_round": 5}), encoding="utf-8")
    assert SimulationRunner._resume_checkpoint_round(str(sim_dir)) == 7


def test_resume_checkpoint_round_rejects_invalid(sim_env):
    sim_dir = sim_env / "sim_run7_bad"
    (sim_dir / "twitter").mkdir(parents=True)
    (sim_dir / "twitter" / "checkpoint.json").write_text("not-json", encoding="utf-8")
    assert SimulationRunner._resume_checkpoint_round(str(sim_dir)) is None
    # completed_round=0（尚未完成任何轮）不可续跑
    (sim_dir / "twitter" / "checkpoint.json").write_text(
        json.dumps({"completed_round": 0}), encoding="utf-8")
    assert SimulationRunner._resume_checkpoint_round(str(sim_dir)) is None


def test_resume_checkpoint_round_config_hash_gate(sim_env):
    # ITEM 3: 检查点 config_hash 与当前 simulation_config.json 指纹匹配则可续跑，不匹配则阻断。
    import hashlib
    sim_dir = sim_env / "sim_item3_hash"
    (sim_dir / "twitter").mkdir(parents=True)
    cfg = {"agent_configs": [{"agent_id": 1}], "time_config": {"minutes_per_round": 60}}
    (sim_dir / "simulation_config.json").write_text(
        json.dumps(cfg), encoding="utf-8")
    cur = hashlib.sha256(
        json.dumps(cfg, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    # 指纹匹配 → 可续跑
    (sim_dir / "twitter" / "checkpoint.json").write_text(
        json.dumps({"completed_round": 6, "config_hash": cur}), encoding="utf-8")
    assert SimulationRunner._resume_checkpoint_round(str(sim_dir)) == 6
    # 指纹不匹配（配置已变更）→ 阻断续跑
    (sim_dir / "twitter" / "checkpoint.json").write_text(
        json.dumps({"completed_round": 6, "config_hash": "deadbeef"}), encoding="utf-8")
    assert SimulationRunner._resume_checkpoint_round(str(sim_dir)) is None
    # 无 config_hash 字段（旧检查点）→ 不阻断（向后兼容）
    (sim_dir / "twitter" / "checkpoint.json").write_text(
        json.dumps({"completed_round": 6}), encoding="utf-8")
    assert SimulationRunner._resume_checkpoint_round(str(sim_dir)) == 6


def test_run_state_persists_resumed_from_round(sim_env):
    sim_id = "sim_run7_state"
    state = SimulationRunState(
        simulation_id=sim_id, runner_status=RunnerStatus.RUNNING, resumed_from_round=9)
    SimulationRunner._save_run_state(state)
    SimulationRunner._run_states.clear()
    loaded = SimulationRunner.get_run_state(sim_id)
    assert loaded.resumed_from_round == 9
    assert loaded.to_dict()["resumed_from_round"] == 9


# ---------------------------------------------------------------- RUN-7 (script side)
def test_round_checkpoint_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SIM_RESUME", "true")
    os.makedirs(tmp_path / "twitter")
    rps._write_round_checkpoint(str(tmp_path), "twitter",
                                completed_round=12, last_rowid=345,
                                total_rounds=36, total_actions=88)
    ckpt = rps._load_round_checkpoint(str(tmp_path), "twitter")
    assert ckpt["completed_round"] == 12
    assert ckpt["last_rowid"] == 345
    assert ckpt["total_actions"] == 88


def test_round_checkpoint_default_writes_without_resume(tmp_path, monkeypatch):
    # ITEM 3: SIM_CHECKPOINT 默认 true——即使未开启 SIM_RESUME 也逐轮落盘，使崩溃后可续跑。
    monkeypatch.delenv("SIM_RESUME", raising=False)
    monkeypatch.delenv("SIM_CHECKPOINT", raising=False)
    os.makedirs(tmp_path / "twitter")
    rps._write_round_checkpoint(str(tmp_path), "twitter", 1, 1, 10, 1)
    assert os.path.exists(rps._checkpoint_file(str(tmp_path), "twitter"))


def test_round_checkpoint_disabled_when_sim_checkpoint_false(tmp_path, monkeypatch):
    # ITEM 3: 显式 SIM_CHECKPOINT=false 且未开 SIM_RESUME → 完全不产出 checkpoint.json（degrade-safe）。
    monkeypatch.delenv("SIM_RESUME", raising=False)
    # 环境防漏：_cfg_flag 在环境变量缺失时回退 Config；开发机 .env 里 SIM_RESUME=true
    # 会经 Config.SIM_RESUME 泄漏进来把检查点强制打开。两条通道都必须被隔离。
    from app.config import Config as _Cfg
    monkeypatch.setattr(_Cfg, "SIM_RESUME", False, raising=False)
    monkeypatch.setenv("SIM_CHECKPOINT", "false")
    os.makedirs(tmp_path / "twitter")
    rps._write_round_checkpoint(str(tmp_path), "twitter", 1, 1, 10, 1)
    assert not os.path.exists(rps._checkpoint_file(str(tmp_path), "twitter"))


def test_round_checkpoint_sim_resume_forces_write_even_if_checkpoint_off(tmp_path, monkeypatch):
    # ITEM 3 向后兼容：SIM_RESUME=true 隐含写检查点，即使 SIM_CHECKPOINT=false 也照写。
    monkeypatch.setenv("SIM_RESUME", "true")
    monkeypatch.setenv("SIM_CHECKPOINT", "false")
    os.makedirs(tmp_path / "reddit")
    rps._write_round_checkpoint(str(tmp_path), "reddit", 2, 5, 10, 9)
    assert os.path.exists(rps._checkpoint_file(str(tmp_path), "reddit"))


def test_checkpoint_config_hash_and_rng_roundtrip(tmp_path, monkeypatch):
    # ITEM 3: config_hash 稳定且随配置变化；rng_state 可随检查点往返落盘/读取。
    monkeypatch.setenv("SIM_CHECKPOINT", "true")
    os.makedirs(tmp_path / "twitter")
    cfg = {"agent_configs": [{"agent_id": 1}], "time_config": {"minutes_per_round": 60}}
    h = rps._config_hash(cfg)
    assert h and rps._config_hash(cfg) == h              # 稳定：同 config 同指纹
    assert rps._config_hash({"agent_configs": []}) != h  # 配置变更 → 指纹变
    rng_state = rps._capture_rng_state()
    assert rng_state and "py_random" in rng_state
    rps._write_round_checkpoint(str(tmp_path), "twitter", 3, 9, 20, 40,
                                config_hash=h, rng_state=rng_state)
    ckpt = rps._load_round_checkpoint(str(tmp_path), "twitter")
    assert ckpt["config_hash"] == h
    assert ckpt["rng_state"]["py_random"][0] == rng_state["py_random"][0]


def test_restore_rng_state_reproduces_stream(monkeypatch):
    # ITEM 3: 恢复 RNG 状态后，后续采样序列与捕获点之后的序列逐值一致（确定性可复现）。
    monkeypatch.setenv("SIM_SEED", "12345")
    orig = rps._RNG
    try:
        rps._RNG = rps._build_sampling_rng()
        _ = [rps._RNG.random() for _ in range(5)]   # 推进若干步
        snap = rps._capture_rng_state()
        expected = [rps._RNG.random() for _ in range(5)]
        assert rps._restore_rng_state(snap) is True
        got = [rps._RNG.random() for _ in range(5)]
        assert got == expected
    finally:
        rps._RNG = orig                              # 隔离：不污染其它测试的模块级 RNG


def test_restore_rng_state_rejects_garbage():
    # ITEM 3: 非法/缺失 RNG 状态一律降级为 False（不崩溃）。
    assert rps._restore_rng_state(None) is False
    assert rps._restore_rng_state({}) is False
    assert rps._restore_rng_state({"py_random": None}) is False


def test_load_round_checkpoint_rejects_zero_rounds(tmp_path):
    os.makedirs(tmp_path / "reddit")
    with open(rps._checkpoint_file(str(tmp_path), "reddit"), "w", encoding="utf-8") as f:
        json.dump({"completed_round": 0}, f)
    assert rps._load_round_checkpoint(str(tmp_path), "reddit") is None


def test_max_trace_rowid(tmp_path):
    db = str(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE trace (user_id INT, action TEXT, info TEXT)")
    conn.executemany("INSERT INTO trace VALUES (?, ?, ?)",
                     [(1, "sign_up", "{}"), (2, "create_post", "{}")])
    conn.commit()
    conn.close()
    assert rps._max_trace_rowid(db) == 2
    assert rps._max_trace_rowid(str(tmp_path / "missing.db")) == 0


def test_run_simulation_signatures_accept_resume():
    import inspect
    assert "resume" in inspect.signature(rps.run_twitter_simulation).parameters
    assert "resume" in inspect.signature(rps.run_reddit_simulation).parameters


# ---------------------------------------------------------------- XRUN-4
def test_free_disk_error_disabled_and_triggered(tmp_path, monkeypatch):
    monkeypatch.setenv("SIM_MIN_FREE_DISK_GB", "0")
    assert rps._free_disk_error(str(tmp_path)) is None
    monkeypatch.setenv("SIM_MIN_FREE_DISK_GB", "999999")
    err = rps._free_disk_error(str(tmp_path))
    assert err is not None and "SIM_MIN_FREE_DISK_GB" in err


def test_step_failure_limit_env(monkeypatch):
    monkeypatch.setenv("SIM_STEP_FAILURE_LIMIT", "5")
    assert rps._step_failure_limit() == 5
    monkeypatch.setenv("SIM_STEP_FAILURE_LIMIT", "0")
    assert rps._step_failure_limit() == 0
    monkeypatch.setenv("SIM_STEP_FAILURE_LIMIT", "abc")
    assert rps._step_failure_limit() == 3


# ---------------------------------------------------------------- XRUN-2
_TOOLS = [{
    "type": "function",
    "function": {
        "name": "create_post",
        "description": "Create a post",
        "parameters": {"type": "object", "properties": {"content": {"type": "string"}}},
    },
}]


def test_parse_tool_call_text_valid():
    content, calls = oasis_llm._parse_tool_call_text(
        '{"tool": "create_post", "arguments": {"content": "hi"}}', {"create_post"})
    assert calls == [{"name": "create_post", "arguments": {"content": "hi"}}]


def test_parse_tool_call_text_null_tool_and_garbage():
    content, calls = oasis_llm._parse_tool_call_text(
        '{"tool": null, "reply": "nothing to do"}', {"create_post"})
    assert calls == [] and content == "nothing to do"
    content, calls = oasis_llm._parse_tool_call_text("plain text", {"create_post"})
    assert calls == [] and content == "plain text"
    # 幻觉工具名不得放行
    _, calls = oasis_llm._parse_tool_call_text(
        '{"tool": "rm_rf", "arguments": {}}', {"create_post"})
    assert calls == []


def test_build_chat_completion_with_tool_calls():
    comp = oasis_llm._build_chat_completion(
        "claude-cli", [{"role": "user", "content": "x"}], "",
        [{"name": "create_post", "arguments": {"content": "hi"}}])
    choice = comp.choices[0]
    assert choice.finish_reason == "tool_calls"
    tc = choice.message.tool_calls[0]
    assert tc.function.name == "create_post"
    assert json.loads(tc.function.arguments) == {"content": "hi"}
    assert choice.message.content  # 绝不产生空 assistant 内容（S2-llm）


class _StubLLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def chat(self, messages, temperature=0.7, max_tokens=4096, **kw):
        self.calls.append(messages)
        return self.reply


def test_cli_model_emulates_tool_calls(monkeypatch):
    monkeypatch.setenv("SIM_CLI_TOOL_EMULATION", "true")
    model = oasis_llm.CLIModel(
        model_type="claude-cli", provider="claude-cli",
        model_config_dict={}, api_key="cli-bridge")
    stub = _StubLLM('{"tool": "create_post", "arguments": {"content": "hello"}}')
    model._llm = stub
    comp = model._request_chat_completion(
        [{"role": "user", "content": "act"}], tools=_TOOLS)
    assert comp.choices[0].finish_reason == "tool_calls"
    assert comp.choices[0].message.tool_calls[0].function.name == "create_post"
    # 工具清单必须进入 prompt（追加的 user 指令块）
    assert any("create_post" in str(m.get("content", "")) for m in stub.calls[0])


def test_cli_model_emulation_off_ignores_tools(monkeypatch):
    monkeypatch.setenv("SIM_CLI_TOOL_EMULATION", "false")
    model = oasis_llm.CLIModel(
        model_type="claude-cli", provider="claude-cli",
        model_config_dict={}, api_key="cli-bridge")
    model._llm = _StubLLM("plain reply")
    comp = model._request_chat_completion(
        [{"role": "user", "content": "act"}], tools=_TOOLS)
    assert comp.choices[0].finish_reason == "stop"
    assert not comp.choices[0].message.tool_calls


def test_cli_model_no_second_tool_call_after_tool_result(monkeypatch):
    monkeypatch.setenv("SIM_CLI_TOOL_EMULATION", "true")
    model = oasis_llm.CLIModel(
        model_type="claude-cli", provider="claude-cli",
        model_config_dict={}, api_key="cli-bridge")
    model._llm = _StubLLM("done")
    comp = model._request_chat_completion(
        [{"role": "user", "content": "act"},
         {"role": "tool", "content": "post created"}], tools=_TOOLS)
    # 已有工具结果 → 纯文本收尾，避免文本协议下的无界工具循环
    assert comp.choices[0].finish_reason == "stop"


# ---------------------------------------------------------------- RUN-18
class _DummyOpenAIModel:
    model_type = "MiniMax-M3"
    model_config_dict = {}

    def __init__(self, exc):
        self._exc = exc

        def _raise(messages, tools=None):
            raise self._exc
        self._request_chat_completion = _raise


def test_fallback_guard_reroutes_content_filter(monkeypatch):
    monkeypatch.setenv("SIM_LLM_FALLBACK", "true")
    monkeypatch.setenv("SIM_CLI_TOOL_EMULATION", "true")

    class _FactoryStub:
        def __init__(self, provider=None, **kw):
            self.provider = provider

        def chat(self, messages, temperature=0.7, max_tokens=4096, **kw):
            return '{"tool": "create_post", "arguments": {"content": "rescued"}}'

    monkeypatch.setattr(oasis_llm, "LLMClient", _FactoryStub)
    model = _DummyOpenAIModel(Exception("Error code: 422 - new_sensitive"))
    oasis_llm._wrap_openai_fallback_guard(model, "minimax")

    before = oasis_llm.get_llm_fallback_stats()["llm_fallback_calls"]
    comp = model._request_chat_completion(
        [{"role": "user", "content": "geo"}], tools=_TOOLS)
    assert comp.choices[0].finish_reason == "tool_calls"
    assert comp.choices[0].message.tool_calls[0].function.name == "create_post"
    after = oasis_llm.get_llm_fallback_stats()
    assert after["llm_fallback_calls"] == before + 1
    assert after["llm_fallback_tool_calls"] >= 1


def test_fallback_guard_reraises_unrelated_errors(monkeypatch):
    monkeypatch.setenv("SIM_LLM_FALLBACK", "true")
    model = _DummyOpenAIModel(ValueError("totally unrelated boom"))
    oasis_llm._wrap_openai_fallback_guard(model, "minimax")
    with pytest.raises(ValueError):
        model._request_chat_completion([{"role": "user", "content": "x"}])


def test_fallback_guard_disabled_by_flag(monkeypatch):
    monkeypatch.setenv("SIM_LLM_FALLBACK", "false")
    model = _DummyOpenAIModel(Exception("Error code: 422 - new_sensitive"))
    oasis_llm._wrap_openai_fallback_guard(model, "minimax")
    with pytest.raises(Exception, match="422"):
        model._request_chat_completion([{"role": "user", "content": "x"}])


def test_fallback_failure_raises_original_error(monkeypatch):
    monkeypatch.setenv("SIM_LLM_FALLBACK", "true")

    class _BrokenFactory:
        def __init__(self, provider=None, **kw):
            pass

        def chat(self, *a, **kw):
            raise RuntimeError("fallback also dead")

    monkeypatch.setattr(oasis_llm, "LLMClient", _BrokenFactory)
    original = Exception("Error code: 429 rate_limit")
    model = _DummyOpenAIModel(original)
    oasis_llm._wrap_openai_fallback_guard(model, "minimax")
    with pytest.raises(Exception, match="429"):
        model._request_chat_completion([{"role": "user", "content": "x"}])
