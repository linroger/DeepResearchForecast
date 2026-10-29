"""CAL-TEMPORAL spec §7 item 2 — 跨模块契约测试套件（presence-keyed 分派）。

钉住日历时序改造在模块边界上的七条契约（全部离线：零 LLM / 零网络 / 零真子进程）：

  1) 分派只看 simulation_config.json 是否带 temporal_config.mode=="calendar"：
     带 → 运行器 total_rounds == n_rounds；不带 → 旧公式 hours*60/minutes（回归钉，
     run_state.json 不出现任何日历新键，逐字节兼容）；
  2) 日历模式运行器忽略运行时 max_rounds（告警 + options.max_rounds_ignored，
     绝不截断预测期；hours 模式截断行为照旧）；
  3) 显式回合上限在配置生成期粗化时间粒度并记 round_cap_coarsened（覆盖仍到判定日）；
  4) 降级路径：问题文本无可解析判定日 + LLM 兜底故障 → 12 个月默认时间线
     （source=="default"、warning 在案、绝不抛异常）；
  5) world_state_seed 注入不再依赖 SIM_DECISION_CHANNEL 开关（日历模式无条件注入，
     并从 temporal_config 补判定日字段）；
  6) run_summary 带全套日历记账字段，同时 simulated_hours 仍走旧公式
     （兼容垫片使其 = 轮数，既有 pinned 测试不动）；
  7) 预测骨架（derive_forecast_spine）拿到的 horizon 是判定日 horizon_date，
     不再是 as_of_date（hours 模式保持旧行为）。

运行器测试用假 subprocess.Popen + 空转监控线程（沿用 test_audit_fixes_runner 的
sim_env 隔离约定）；配置生成器按 test_calendar_event_bucketing 约定以 __new__ 构建。
"""

import inspect
import json
import logging
import os
import sys
from dataclasses import asdict

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services import pipeline_orchestrator as po  # noqa: E402
from app.services.report_agent import ReportAgent  # noqa: E402
from app.services.simulation_config_generator import SimulationConfigGenerator  # noqa: E402
from app.services.simulation_runner import SimulationRunner  # noqa: E402
import app.services.simulation_runner as sr_mod  # noqa: E402


# ─────────────────────────────── 共享夹具 ───────────────────────────────

_ROUND_DATES = [
    {"round": 0, "period_start": "2026-07-12", "period_end": "2026-09-30", "label": "2026-Q3"},
    {"round": 1, "period_start": "2026-10-01", "period_end": "2026-12-31", "label": "2026-Q4"},
    {"round": 2, "period_start": "2027-01-01", "period_end": "2027-03-31", "label": "2027-Q1"},
]


def _temporal_block():
    """spec §3 形态的 temporal_config（3 个季度回合，判定日 2027-03-31）。"""
    return {
        "schema_version": 1, "mode": "calendar",
        "as_of_date": "2026-07-11", "horizon_date": "2027-03-31",
        "horizon_source": "anchored_period", "horizon_text": "Q1 2027",
        "horizon_defaulted": False,
        "unit": "quarter", "unit_stride": 1, "n_rounds": 3,
        "round_dates": list(_ROUND_DATES),
        "span_days": 263, "target_max_rounds": 36,
        "round_cap_coarsened": None, "beyond_horizon_events": [], "warnings": [],
    }


@pytest.fixture
def sim_env(tmp_path, monkeypatch):
    """隔离 RUN_STATE_DIR + 清空运行器内存注册表（沿用 test_audit_fixes_runner 约定）。"""
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationRunner, "_run_states", {})
    monkeypatch.setattr(SimulationRunner, "_run_state_last_save", {})
    monkeypatch.setattr(SimulationRunner, "_processes", {})
    monkeypatch.setattr(SimulationRunner, "_action_queues", {})
    monkeypatch.setattr(SimulationRunner, "_monitor_threads", {})
    monkeypatch.setattr(SimulationRunner, "_stdout_files", {})
    monkeypatch.setattr(SimulationRunner, "_stderr_files", {})
    monkeypatch.setattr(SimulationRunner, "_graph_memory_enabled", {})
    monkeypatch.setattr(SimulationRunner, "_cleanup_done", True, raising=False)
    return tmp_path


class _FakeProc:
    """subprocess.Popen 替身——只提供 start_simulation 用到的 pid/poll。"""

    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.pid = os.getpid()

    def poll(self):
        return None


@pytest.fixture
def no_subprocess(monkeypatch):
    """把子进程与监控线程换成替身：start_simulation 全程进程内、确定性。"""
    procs = []

    def _popen(cmd, **kwargs):
        proc = _FakeProc(cmd, **kwargs)
        procs.append(proc)
        return proc

    monkeypatch.setattr(sr_mod.subprocess, "Popen", _popen)
    # 监控线程空转（daemon 线程立即返回，不读日志不改状态）
    monkeypatch.setattr(SimulationRunner, "_monitor_simulation", lambda simulation_id: None)
    monkeypatch.setattr(Config, "SIM_RESUME", False, raising=False)
    return procs


def _prepare_sim(sim_env, sim_id, config):
    sim_dir = sim_env / sim_id
    sim_dir.mkdir()
    (sim_dir / "simulation_config.json").write_text(
        json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return sim_dir


def _read_run_state(sim_dir):
    with open(os.path.join(str(sim_dir), "run_state.json"), encoding="utf-8") as f:
        return json.load(f)


class _ListHandler(logging.Handler):
    """捕获运行器 logger 的 WARNING 记录（mirofish.* propagate=False，caplog 收不到）。"""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records = []

    def emit(self, record):
        self.records.append(record)


# ══════════════════════ 1) presence-keyed 分派 ══════════════════════

def test_calendar_config_dispatches_runner_to_n_rounds(sim_env, no_subprocess):
    """带 temporal_config.mode=="calendar" → total_rounds == n_rounds（单一权威）。

    故意让 time_config 的旧公式给出不同值（99 轮），证明日历分支读的是
    temporal_config.n_rounds 而非兼容垫片公式。
    """
    sim_id = "sim_cal_dispatch"
    cfg = {
        "temporal_config": _temporal_block(),
        "time_config": {"total_simulation_hours": 99, "minutes_per_round": 60},
    }
    sim_dir = _prepare_sim(sim_env, sim_id, cfg)

    state = SimulationRunner.start_simulation(sim_id, platform="parallel")

    assert state.total_rounds == 3            # = n_rounds，而非 99*60/60
    assert state.temporal_mode == "calendar"
    assert state.calendar_unit == "quarter"
    assert state.horizon_date == "2027-03-31"
    assert state.rounds_truncated_from is None and state.rounds_truncated_to is None
    assert "max_rounds_ignored" not in state.options
    # run_state.json 序列化带日历字段
    data = _read_run_state(sim_dir)
    assert data["total_rounds"] == 3
    assert data["temporal_mode"] == "calendar"
    assert data["calendar_unit"] == "quarter"
    assert data["horizon_date"] == "2027-03-31"


def test_hours_config_legacy_formula_regression_pin(sim_env, no_subprocess):
    """无 temporal_config → 旧公式 total_rounds = hours*60/minutes，回归钉。

    Calendar fields stay absent. The separately introduced record-finalization
    ownership/token remain required on the hours path as well.
    """
    sim_id = "sim_hours_legacy"
    cfg = {"time_config": {"total_simulation_hours": 72, "minutes_per_round": 30}}
    sim_dir = _prepare_sim(sim_env, sim_id, cfg)

    state = SimulationRunner.start_simulation(sim_id, platform="parallel")

    assert state.total_rounds == 144          # int(72 * 60 / 30)
    assert state.temporal_mode is None
    data = _read_run_state(sim_dir)
    for key in ("temporal_mode", "calendar_unit", "current_period_end", "horizon_date"):
        assert key not in data
    assert set(data["options"]) == {"record_owner", "terminal_artifacts_token"}
    assert data["options"]["record_owner"] == "runner"
    token = data["options"]["terminal_artifacts_token"]
    assert isinstance(token, str) and len(token) == 32 and all(c in "0123456789abcdef" for c in token)


def test_hours_config_max_rounds_still_truncates(sim_env, no_subprocess):
    """hours 模式 max_rounds 截断行为照旧（T3.7 一等字段记账，回归钉）。"""
    sim_id = "sim_hours_truncate"
    cfg = {"time_config": {"total_simulation_hours": 72, "minutes_per_round": 30}}
    _prepare_sim(sim_env, sim_id, cfg)

    state = SimulationRunner.start_simulation(sim_id, platform="parallel", max_rounds=5)

    assert state.total_rounds == 5
    assert state.rounds_truncated_from == 144
    assert state.rounds_truncated_to == 5
    assert "max_rounds_ignored" not in state.options


# ═════════════════ 2) 日历模式忽略运行时 max_rounds ═════════════════

def test_calendar_runner_ignores_max_rounds_with_warning(sim_env, no_subprocess):
    """日历模式运行时 max_rounds 绝不截断：告警 + options.max_rounds_ignored 记账。"""
    sim_id = "sim_cal_ignore_cap"
    cfg = {
        "temporal_config": _temporal_block(),
        "time_config": {"total_simulation_hours": 3, "minutes_per_round": 60},
    }
    sim_dir = _prepare_sim(sim_env, sim_id, cfg)

    handler = _ListHandler()
    runner_logger = logging.getLogger("mirofish.simulation_runner")
    runner_logger.addHandler(handler)
    try:
        state = SimulationRunner.start_simulation(
            sim_id, platform="parallel", max_rounds=1)
    finally:
        runner_logger.removeHandler(handler)

    assert state.total_rounds == 3            # 未被 max_rounds=1 截断
    assert state.options.get("max_rounds_ignored") is True
    assert state.rounds_truncated_from is None and state.rounds_truncated_to is None
    # 告警确实发出且指名 max_rounds
    warned = [r.getMessage() for r in handler.records]
    assert any("max_rounds" in m for m in warned)
    # 记账持久化到 run_state.json
    data = _read_run_state(sim_dir)
    assert data["options"]["max_rounds_ignored"] is True


# ═══════════ 3) 回合上限 → 粗化粒度并记 round_cap_coarsened ═══════════

def _bare_generator():
    """按既有测试约定用 __new__ 构建（不触碰 LLMClient 构造）。"""
    return SimulationConfigGenerator.__new__(SimulationConfigGenerator)


def _patch_calendar_knobs(monkeypatch):
    monkeypatch.setattr(Config, "SIM_CALENDAR_TARGET_MAX_ROUNDS", 36, raising=False)
    monkeypatch.setattr(Config, "SIM_CALENDAR_HARD_MAX_ROUNDS", 48, raising=False)
    monkeypatch.setattr(Config, "SIM_HORIZON_DEFAULT_MONTHS", 12, raising=False)
    monkeypatch.setattr(Config, "OASIS_DEFAULT_MAX_ROUNDS", 0, raising=False)


_ACTORS_2030 = {"as_of_date": "2026-07-11",
                "central_question": "谁会在2030年前赢得美国AI竞赛？"}
_REQ_2030 = "Who wins the US AI race by 2030?"


def test_explicit_round_cap_coarsens_unit_never_truncates(monkeypatch):
    """max_rounds 只降 target_max 粗化时间粒度：单位 quarter→half_year，
    round_cap_coarsened 记账，覆盖仍到判定日 2030-12-31（绝不截断）。"""
    _patch_calendar_knobs(monkeypatch)
    gen = _bare_generator()

    def _no_llm(prompt, system_prompt):  # 确定性层命中 bare_year，不应触达 LLM
        raise AssertionError("确定性判定日抽取命中时不应调用 LLM 兜底")

    gen._call_llm_with_retry = _no_llm

    # 无上限参照：quarter × 18 轮，无粗化记录（spec §2.3 pinned：by 2030 → quarter/18）
    ref = gen._build_temporal_timeline(_REQ_2030, _ACTORS_2030, context="", max_rounds=None)
    assert ref.horizon_date == "2030-12-31" and ref.horizon_source == "bare_year"
    assert ref.unit == "quarter" and ref.n_rounds == 18
    assert ref.round_cap_coarsened is None
    assert "round_cap_coarsened" not in ref.warnings

    # 显式 max_rounds=10 → 粗化到 half_year × 9 轮，覆盖不变
    capped = gen._build_temporal_timeline(_REQ_2030, _ACTORS_2030, context="", max_rounds=10)
    assert capped.unit == "half_year" and capped.n_rounds == 9
    assert capped.round_cap_coarsened == {
        "from_unit": "quarter", "to_unit": "half_year", "cap": 10}
    assert "round_cap_coarsened" in capped.warnings
    # 绝不截断预测期：最后一个回合仍恰好止于判定日
    assert capped.round_dates[-1].period_end == capped.horizon_date == "2030-12-31"
    assert capped.n_rounds == len(capped.round_dates) <= 10


def test_timeline_serializes_spec_schema_keys(monkeypatch):
    """generator → temporal_config 的序列化形态（asdict）覆盖 spec §3 全部键。"""
    _patch_calendar_knobs(monkeypatch)
    gen = _bare_generator()
    gen._call_llm_with_retry = lambda p, s: (_ for _ in ()).throw(AssertionError("no LLM"))
    tl = gen._build_temporal_timeline(_REQ_2030, _ACTORS_2030, context="", max_rounds=None)
    data = asdict(tl)
    assert set(data) == {
        "schema_version", "mode", "as_of_date", "horizon_date", "horizon_source",
        "horizon_text", "horizon_defaulted", "unit", "unit_stride", "n_rounds",
        "round_dates", "span_days", "target_max_rounds", "round_cap_coarsened",
        "beyond_horizon_events", "warnings",
    }
    assert data["schema_version"] == 1 and data["mode"] == "calendar"
    assert data["round_dates"][0] == {
        "round": 0, "period_start": "2026-07-12",
        "period_end": "2026-09-30", "label": "2026-Q3"}
    assert data["n_rounds"] == len(data["round_dates"])


# ══════════ 4) 降级路径：无判定日 + LLM 故障 → 12 个月默认 ══════════

_NO_DATE_REQ = "谁将在监管博弈中占据上风？"
_NO_DATE_ACTORS = {"as_of_date": "2026-07-11", "central_question": "监管博弈的结局如何？"}


def test_degrade_no_horizon_llm_failure_defaults_12_months(monkeypatch):
    """确定性四层落空 + LLM 兜底抛异常 → 默认 12 个月时间线，绝不抛出。"""
    _patch_calendar_knobs(monkeypatch)
    gen = _bare_generator()
    calls = {"n": 0}

    def _boom(prompt, system_prompt):
        calls["n"] += 1
        raise RuntimeError("LLM 故障（注入）")

    gen._call_llm_with_retry = _boom

    tl = gen._build_temporal_timeline(
        _NO_DATE_REQ, _NO_DATE_ACTORS, context="背景材料（无期限线索）", max_rounds=None)

    assert calls["n"] == 1                       # LLM 兜底确实被尝试，故障被吞
    assert tl.horizon_source == "default"
    assert tl.horizon_defaulted is True
    assert tl.horizon_date == "2027-07-11"       # as_of + 12 个月（真日历加法）
    assert "horizon_defaulted_12_months" in tl.warnings
    assert "as_of_defaulted" not in tl.warnings  # as_of 可解析，不误报
    # 12 个月跨度 → month 单位；n_rounds 恒等于实际边界数（首段 7-12~7-31 为残段保留）
    assert tl.unit == "month"
    assert tl.n_rounds == len(tl.round_dates) == 13
    assert tl.round_dates[-1].period_end == "2027-07-11"


def test_degrade_llm_out_of_range_horizon_discarded(monkeypatch):
    """LLM 兜底返回越界日期（≤ as_of）→ 丢弃，仍降级到 12 个月默认。"""
    _patch_calendar_knobs(monkeypatch)
    gen = _bare_generator()
    gen._call_llm_with_retry = lambda p, s: {"horizon_date": "2020-01-01"}

    tl = gen._build_temporal_timeline(
        _NO_DATE_REQ, _NO_DATE_ACTORS, context="", max_rounds=None)

    assert tl.horizon_source == "default" and tl.horizon_defaulted is True
    assert tl.horizon_date == "2027-07-11"
    assert "horizon_defaulted_12_months" in tl.warnings


# ═════════ 5) world_state_seed 不再依赖 SIM_DECISION_CHANNEL ═════════

def test_world_state_seed_gate_calendar_bypasses_decision_channel_flag():
    """注入门是「日历模式 OR SIM_DECISION_CHANNEL」，且日历分支空情景也注入、
    并从 temporal_config 补判定日字段。

    该块内联在 PipelineOrchestrator._run 的 RUN 阶段前（无法离线驱动完整管线），
    以源码契约钉住关键行：任何改回「仅 SIM_DECISION_CHANNEL 才注入」的回归都会命中。
    """
    src = inspect.getsource(po)
    # 日历判定与门控表达式（_cal_gen 在前 —— 日历模式单独即可触发注入）
    assert "_cal_gen = _calendar_mode()" in src
    assert ('if (_cal_gen or getattr(Config, "SIM_DECISION_CHANNEL", False)) '
            "and not _run_already_done:") in src
    # 日历模式空 scenarios 也注入（运行侧对空情景静默关演化）
    assert 'if _cal_gen or _seed.get("scenarios"):' in src
    # 判定日字段以 temporal_config 为准补入种子
    assert '_seed["horizon_date"] = _tc.get("horizon_date") or _seed.get("horizon_date")' in src
    assert '_seed["horizon_source"] = _tc.get("horizon_source")' in src
    assert '_seed["horizon_defaulted"] = bool(_tc.get("horizon_defaulted"))' in src
    assert '_wcfg["world_state_seed"] = _seed' in src


def test_calendar_mode_helper_reads_generation_flag(monkeypatch):
    """_calendar_mode 只读 Config.SIM_TEMPORAL_MODE（生成语义），老 Config 缺属性 → False。"""
    monkeypatch.setattr(Config, "SIM_TEMPORAL_MODE", "calendar", raising=False)
    assert po._calendar_mode() is True
    monkeypatch.setattr(Config, "SIM_TEMPORAL_MODE", "hours", raising=False)
    assert po._calendar_mode() is False
    monkeypatch.delattr(Config, "SIM_TEMPORAL_MODE", raising=False)
    assert po._calendar_mode() is False


# ══════ 6) run_summary：日历字段 + simulated_hours 仍走旧公式 ══════

def _write_actions(sim_dir, platform, entries):
    plat_dir = os.path.join(str(sim_dir), platform)
    os.makedirs(plat_dir, exist_ok=True)
    with open(os.path.join(plat_dir, "actions.jsonl"), "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _organic_entries(rounds):
    return [{"round": r, "timestamp": f"2026-07-12T00:0{r}:00", "agent_id": r,
             "agent_name": f"A{r}", "action_type": "CREATE_POST",
             "action_args": {"content": f"post {r}"}} for r in rounds]


def _summary_sim(sim_env, sim_id, run_state, with_temporal=True, rounds=(1, 2, 3)):
    sim_dir = sim_env / sim_id
    _write_actions(sim_dir, "twitter", _organic_entries(list(rounds)))
    cfg = {"time_config": {"total_simulation_hours": 3, "minutes_per_round": 60}}
    if with_temporal:
        cfg["temporal_config"] = _temporal_block()
    (sim_dir / "simulation_config.json").write_text(
        json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    (sim_dir / "run_state.json").write_text(json.dumps(run_state), encoding="utf-8")
    return sim_dir


def test_run_summary_carries_calendar_fields_and_legacy_hours(sim_env):
    sim_id = "sim_summary_cal"
    sim_dir = _summary_sim(sim_env, sim_id, {
        "current_round": 3, "total_rounds": 3, "current_period_end": "2027-03-31"})

    summary = SimulationRunner.write_run_summary(sim_id)

    assert summary["temporal_mode"] == "calendar"
    assert summary["calendar_unit"] == "quarter"
    assert summary["total_periods"] == 3
    assert summary["horizon_date"] == "2027-03-31"
    assert summary["horizon_source"] == "anchored_period"
    assert summary["horizon_defaulted"] is False
    assert summary["coverage_end"] == "2027-03-31"       # run_state 实时推进值优先
    assert summary["simulated_span_days"] == 263          # 2026-07-11 → 2027-03-31
    # 契约核心：simulated_hours 仍是旧公式 rounds×minutes/60（垫片使其 = 轮数）
    assert summary["simulated_hours"] == 3.0
    assert summary["rounds_executed"] == 3
    # 落盘产物与返回值一致
    with open(os.path.join(str(sim_dir), "run_summary.json"), encoding="utf-8") as f:
        on_disk = json.load(f)
    for key in ("temporal_mode", "calendar_unit", "total_periods", "horizon_date",
                "horizon_source", "horizon_defaulted", "coverage_end",
                "simulated_span_days", "simulated_hours"):
        assert on_disk[key] == summary[key]


def test_run_summary_coverage_end_falls_back_to_round_dates(sim_env):
    """run_state 无 current_period_end → 按 rounds_executed 回查 round_dates。"""
    sim_id = "sim_summary_fallback"
    _summary_sim(sim_env, sim_id,
                 {"current_round": 2, "total_rounds": 3}, rounds=(1, 2))

    summary = SimulationRunner.write_run_summary(sim_id)

    assert summary["coverage_end"] == "2026-12-31"        # round_dates[1].period_end
    assert summary["simulated_span_days"] == 173           # 2026-07-11 → 2026-12-31
    assert summary["simulated_hours"] == 2.0               # 旧公式：2 × 60 / 60


def test_run_summary_hours_mode_writes_no_calendar_keys(sim_env):
    """hours 模式（无 temporal_config）→ run_summary 不出现任何日历键（逐字节不变）。"""
    sim_id = "sim_summary_hours"
    _summary_sim(sim_env, sim_id,
                 {"current_round": 3, "total_rounds": 3}, with_temporal=False)

    summary = SimulationRunner.write_run_summary(sim_id)

    for key in ("temporal_mode", "calendar_unit", "total_periods", "horizon_date",
                "horizon_source", "horizon_defaulted", "coverage_end",
                "simulated_span_days"):
        assert key not in summary
    assert summary["simulated_hours"] == 3.0               # 旧公式照旧


# ═══════ 7) 预测骨架拿到 horizon_date 而非 as_of_date ═══════

def _bare_report_agent(**over):
    """ReportAgent 裸构造（沿用 test_audit_fixes_report 的 _bare_agent 约定）。"""
    a = ReportAgent.__new__(ReportAgent)
    a.graph_id = "g1"
    a.simulation_id = "sim1"
    a.simulation_requirement = "谁会赢得竞赛？"
    a.situation_brief = ""
    a.actors = None
    a.sources = []
    a.research_report = ""
    a.output_language = "English"
    a.scenario_label = ""
    a.base_simulation_id = None
    a._background_block = ""
    a._sources_index = ""
    a._signal_pack = "signal"     # 非空 → 跳过 _build_signal_pack
    a._market_pack = "market"     # 非空 → 跳过 _build_market_pack
    a._forecast_spine = None
    a._forecast_spine_block = ""
    a._retrieval_query = None
    a._outline_degraded = False
    a._outline_summary = ""
    a._section_tool_calls = 0
    a.report_logger = None
    a.console_logger = None
    a.tools = {}
    a.llm = None
    for k, v in over.items():
        setattr(a, k, v)
    return a


def _capture_spine(monkeypatch):
    captured = {}

    def _fake_spine(llm, **kwargs):
        captured.update(kwargs)
        return {}  # 无 scenarios → _derive_and_pin_forecast_spine 提前返回

    monkeypatch.setattr(
        "app.services.forecast_extractor.derive_forecast_spine", _fake_spine)
    return captured


def _wire_sim_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))


def test_spine_receives_horizon_date_in_calendar_mode(monkeypatch, tmp_path):
    """日历模式：derive_forecast_spine 的 horizon = temporal_config.horizon_date
    （spec §4 report_agent 骨架 bug 修复——此前误传 as_of_date）。"""
    sim_id = "sim_spine_cal"
    sim_dir = tmp_path / sim_id
    sim_dir.mkdir()
    tc = _temporal_block()
    tc["horizon_date"] = "2030-12-31"
    tc["horizon_source"] = "bare_year"
    (sim_dir / "simulation_config.json").write_text(
        json.dumps({"temporal_config": tc,
                    "time_config": {"total_simulation_hours": 3,
                                    "minutes_per_round": 60}},
                   ensure_ascii=False), encoding="utf-8")
    # v3 轨迹同样带判定日（trajectory/config 两个来源一致，实施可取任一）
    (sim_dir / "world_state_trajectory.json").write_text(
        json.dumps({"schema_version": 3, "mode": "calendar",
                    "calendar_unit": "quarter", "horizon_date": "2030-12-31",
                    "horizon_source": "bare_year", "horizon_defaulted": False,
                    "trajectory": [], "decisions": [], "outcome": {}},
                   ensure_ascii=False), encoding="utf-8")
    _wire_sim_dirs(monkeypatch, tmp_path)
    captured = _capture_spine(monkeypatch)

    agent = _bare_report_agent(simulation_id=sim_id,
                               actors={"as_of_date": "2026-07-11"})
    agent._derive_and_pin_forecast_spine("report_spine_cal")

    assert captured.get("horizon") == "2030-12-31", (
        "日历模式骨架必须拿判定日 horizon_date（2030-12-31），"
        f"而非 as_of_date；实际收到 {captured.get('horizon')!r}")


def test_spine_hours_mode_keeps_as_of_date(monkeypatch, tmp_path):
    """hours 模式（无 temporal_config / 无 v3 轨迹）→ 旧行为：horizon = as_of_date。"""
    sim_id = "sim_spine_hours"
    sim_dir = tmp_path / sim_id
    sim_dir.mkdir()
    (sim_dir / "simulation_config.json").write_text(
        json.dumps({"time_config": {"total_simulation_hours": 72,
                                    "minutes_per_round": 60}}), encoding="utf-8")
    _wire_sim_dirs(monkeypatch, tmp_path)
    captured = _capture_spine(monkeypatch)

    agent = _bare_report_agent(simulation_id=sim_id,
                               actors={"as_of_date": "2026-07-11"})
    agent._derive_and_pin_forecast_spine("report_spine_hours")

    assert captured.get("horizon") == "2026-07-11"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-x", "-q"]))
