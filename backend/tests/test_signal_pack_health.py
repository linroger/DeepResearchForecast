"""REPORT-5 — fail-closed hollow/errored-simulation gate on the report signal pack.

REPORT_SIGNAL_PACK_HEALTH_GATE (default on) makes ReportAgent._build_signal_pack
read ``simulation_health`` from the simulation's run_summary.json (the path the
orchestrator's health gate reads) and:

- hollow: drops the activity-derived blocks (salience tiers from
  simulation_outcomes, coalition_map, scenario_diff) and states under the header
  that the run produced no usable behaviour data; the world-state block (it
  carries its own validity line), projected edges and the causal spine stay;
- errored: additionally drops the world-state block; a pack with no block left
  is '' (no simulation material at all);
- truncated / llm_degraded: keeps every block and adds a caution line;
- an unrecognised non-ok value: keeps every block, adds its own caution line and
  logs a warning (the gate leans closed instead of treating it as ok);
- ok, a missing or unreadable summary, or the knob off: the legacy pack,
  byte-identical. A summary that exists but cannot be read is additionally
  flagged (summary_unreadable) and logged at WARNING, since the gate did not run.

The verdict is kept on the agent and written to forecast.json as
quality.signal_pack_health. Offline: tmp run-state dir, stub tools, no LLM.

FU-3 extends the same rule to the outline prompt's simulation sweeps, the ReACT
tools (simulation_outcomes, coalition_map incl. faction_brief's fallback,
opinion_shift, scenario_diff) and every consumer of a what-if report's baseline
(signal-pack diff block, comparison table, scenario_diff tool, outline diff
sweep); the baseline verdict is written as quality.baseline_signal_pack_health.
The summary is read once per simulation per report.
"""

import json
import logging
import os
import re
from pathlib import Path

import pytest

import app.config as cfgmod
import app.services.graphiti_client.runtime as rt_mod
from app.config import Config
from app.services.report_agent import (
    PLAN_USER_PROMPT_TEMPLATE, ReportAgent, ReportManager, salience_tiers_from_outcomes)
from app.services.simulation_runner import SimulationRunner
from app.services.zep_tools import ZepToolsService

SIM_ID = "sim_report5"
BASE_SIM_ID = "sim_report5_base"

# The pack header as rendered before REPORT-5 (copied from _build_signal_pack):
# the golden legacy pack is built from it, independently of the gate code path.
_LEGACY_HEADER = (
    "【内部情景推演·诊断材料（elicited model projection——模型引出的推演投影，"
    "非观察证据）】\n"
    "使用规则：以下产出可用于机制分析（权力集中度、联盟结构、脆弱节点、议程设置力"
    "的假设生成），但：\n"
    "✅ 正文引用其任何判断时必须显式标注来源为内部情景推演（如「内部情景推演显示…」），"
    "不得表述为观察到的现实世界事实；\n"
    "✅ 现实世界的定量声明只能来自研究材料并带 [S#] 引用；\n"
    "❌ 严禁依据本材料给出、调整或佐证任何结果概率数字——概率由预测骨架独立裁定，"
    "本材料不进入概率生成路径（forecast_effect=diagnostic_only）；\n"
    "❌ 严禁在正文引用动作次数、轮次、动作类型、发帖/点赞/评论等机制细节。"
)

_WORLD_STATE = ("【推演结果分布 P(outcome)（elicited model projection——模型引出的推演投影，"
                "非观察证据；仅供机制分析，不得据此调整概率）】\n· SCN-A: 60%\n· SCN-B: 40%")
_OUTCOMES = (
    "## 模拟量化结果（结构化，可直接引用）\n\n### 最活跃 Agent（Top 3，按总动作数）\n"
    "- Orion Foundry(id=1): 共 48 次动作 [CREATE_POST×21]\n"
    "- Vega Semis(id=2): 共 40 次动作 [CREATE_COMMENT×12]\n"
    "- Lyra Memory(id=3): 共 5 次动作 [LIKE_POST×5]\n"
)
_TIERS = salience_tiers_from_outcomes(_OUTCOMES)
_COALITIONS = "## 派系/联盟图（关注聚类）\n- 派系 1（3 人）：Orion Foundry、Vega Semis、Lyra Memory"
_SPINE = "【因果骨架（图谱派生）】\n- 出口管制 → 晶圆产能 → 终端价格"
_DIFF = "## 情景对比 / 反事实差异\n- 基线 vs 情景：派系数 2 → 3"
_EDGES = "【关系演化投影（模型先验，非证据）】\n- Orion Foundry ↔ Vega Semis：contingent"
_SHIFT = "## Orion Foundry 逐轮行为轨迹\n- 第 1 轮：3 次动作"

_NO_BEHAVIOUR = ("⚠️ 本次模拟未产出可用的行为数据（simulation_health={health}）——这不是「行为者无反应」"
                 "的发现；正文不得引用任何基于模拟行为量或派系聚类的推演结论。")
_PARTIAL = ("⚠️ 模拟运行状态：{health}（未完整或降级完成）——以下诊断材料只覆盖部分运行，"
            "引用须更加审慎。")
_UNKNOWN = ("⚠️ 模拟运行状态：{health}（未识别的健康状态，运行是否完整未经确认）——以下诊断材料的"
            "可靠性未经核验，引用须更加审慎。")

_ACTIVITY_SUPPRESSED = ["simulation_outcomes", "coalition_map", "scenario_diff"]


def _pack(*blocks: str, note: str = "") -> str:
    """Expected pack: header, optional status line, then the blocks in render order."""
    head = _LEGACY_HEADER + ("\n\n" + note if note else "")
    return head + "\n\n" + "\n\n".join(blocks)


_LEGACY_FULL = _pack(_WORLD_STATE, _TIERS, _COALITIONS, _SPINE, _DIFF)


class _StubZep:
    """Records every simulation-activity tool call; returns fixed rendered blocks."""

    def __init__(self):
        self.calls = []

    def simulation_outcomes(self, simulation_id, top_n=8):
        self.calls.append("simulation_outcomes")
        return _OUTCOMES

    def coalition_map(self, graph_id, simulation_id):
        self.calls.append("coalition_map")
        return _COALITIONS

    def scenario_diff(self, base_simulation_id, simulation_id):
        self.calls.append("scenario_diff")
        return _DIFF

    def opinion_shift(self, simulation_id, actor_name):
        self.calls.append("opinion_shift")
        return _SHIFT


@pytest.fixture
def run_state(tmp_path, monkeypatch):
    """Tmp RUN_STATE_DIR with signal-pack knobs pinned; returns a summary writer."""
    root = tmp_path / "simulations"
    root.mkdir()
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(root))
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "diagnostic_only", raising=False)
    monkeypatch.setattr(Config, "REPORT_SIGNAL_PACK_HEALTH_GATE", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_SIGNAL_PACK_QUALITATIVE", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_CAUSAL_SPINE", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_PROJECTED_EDGES", False, raising=False)

    def write(health=None, *, raw=None):
        sim_dir = root / SIM_ID
        sim_dir.mkdir(exist_ok=True)
        if raw is not None:
            text = raw
        else:
            summary = {"simulation_id": SIM_ID, "organic_action_count": 0 if health == "hollow" else 57}
            if health is not None:
                summary["simulation_health"] = health
            text = json.dumps(summary)
        (sim_dir / "run_summary.json").write_text(text, encoding="utf-8")

    return write


@pytest.fixture
def warnings_log():
    """WARNING+ records of the report agent's logger (mirofish.* does not propagate, so
    caplog misses them): a temporary handler on the real logger."""
    records = []
    handler = logging.Handler(level=logging.WARNING)
    handler.emit = records.append
    log = logging.getLogger("mirofish.report_agent")
    log.addHandler(handler)
    try:
        yield records
    finally:
        log.removeHandler(handler)


def _gate_warnings(records):
    return [r.getMessage() for r in records if "信号包健康门" in r.getMessage()]


def _agent(*, base=BASE_SIM_ID, world_state=_WORLD_STATE, spine=_SPINE):
    a = ReportAgent.__new__(ReportAgent)
    a.simulation_id = SIM_ID
    a.graph_id = "graph_report5"
    a.base_simulation_id = base
    a.actors = [{"name": "Orion Foundry"}]
    a.zep_tools = _StubZep()
    a._signal_pack_health = None
    a._world_state_block = lambda: world_state
    a._build_causal_spine_block = lambda: spine
    return a


# ───────────────────────────── hollow ─────────────────────────────
def test_hollow_suppresses_activity_blocks(run_state):
    run_state("hollow")
    agent = _agent()

    pack = agent._build_signal_pack()

    marker = _NO_BEHAVIOUR.format(health="hollow")
    # the unavailable marker sits directly under the header; world state and the
    # graph-derived causal spine are the only blocks left
    assert pack == _pack(_WORLD_STATE, _SPINE, note=marker)
    assert marker in pack and _SPINE in pack and _WORLD_STATE in pack
    # zero salience / coalition / scenario-diff lines although the tools return data
    assert _TIERS and _TIERS not in pack
    for leaked in ("议程设置力分层", "第一梯队", "Vega Semis", "Lyra Memory",
                   "派系/联盟图", "情景对比", "次动作"):
        assert leaked not in pack
    # the activity tools are not even consulted
    assert agent.zep_tools.calls == []
    assert agent._signal_pack_health == {"health": "hollow", "suppressed": _ACTIVITY_SUPPRESSED}
    assert agent._signal_pack_health["health"] == "hollow"


def test_hollow_without_baseline_does_not_claim_a_suppressed_scenario_diff(run_state):
    run_state("hollow")
    agent = _agent(base=None)

    assert agent._build_signal_pack() == _pack(
        _WORLD_STATE, _SPINE, note=_NO_BEHAVIOUR.format(health="hollow"))
    assert agent._signal_pack_health == {
        "health": "hollow", "suppressed": ["simulation_outcomes", "coalition_map"]}


def test_hollow_with_no_block_left_is_empty(run_state):
    run_state("hollow")
    agent = _agent(world_state="", spine="")

    assert agent._build_signal_pack() == ""
    assert agent.zep_tools.calls == []
    assert agent._signal_pack_health["health"] == "hollow"


def test_health_value_is_normalised(run_state):
    run_state("  HOLLOW ")
    agent = _agent()

    assert agent._build_signal_pack() == _pack(
        _WORLD_STATE, _SPINE, note=_NO_BEHAVIOUR.format(health="hollow"))


# ───────────────────────────── errored ─────────────────────────────
def test_errored_drops_world_state(run_state):
    run_state("errored")
    agent = _agent()

    pack = agent._build_signal_pack()

    assert pack == _pack(_SPINE, note=_NO_BEHAVIOUR.format(health="errored"))
    assert _WORLD_STATE not in pack and "P(outcome)" not in pack
    assert agent.zep_tools.calls == []
    assert agent._signal_pack_health == {
        "health": "errored", "suppressed": ["world_state"] + _ACTIVITY_SUPPRESSED}

    # with no graph-derived block remaining there is no simulation material at all
    bare = _agent(spine="")
    assert bare._build_signal_pack() == ""
    assert bare._signal_pack_health["health"] == "errored"


def test_errored_keeps_graph_derived_blocks(run_state, monkeypatch):
    run_state("errored")
    monkeypatch.setattr(Config, "REPORT_PROJECTED_EDGES", True, raising=False)
    from app.utils import actors as actors_mod
    monkeypatch.setattr(actors_mod, "projected_edges_block", lambda actors: _EDGES)

    pack = _agent()._build_signal_pack()

    assert pack == _pack(_EDGES, _SPINE, note=_NO_BEHAVIOUR.format(health="errored"))


# ─────────────────────── truncated / llm_degraded ───────────────────────
@pytest.mark.parametrize("health", ["truncated", "llm_degraded"])
def test_truncated_caveat(run_state, health):
    run_state(health)
    agent = _agent()

    pack = agent._build_signal_pack()

    caveat = _PARTIAL.format(health=health)
    assert pack == _pack(_WORLD_STATE, _TIERS, _COALITIONS, _SPINE, _DIFF, note=caveat)
    # every block is kept; the caveat is the only difference from the legacy pack
    assert pack.replace("\n\n" + caveat, "", 1) == _LEGACY_FULL
    assert agent.zep_tools.calls == ["simulation_outcomes", "coalition_map", "scenario_diff"]
    assert agent._signal_pack_health == {"health": health, "suppressed": []}


# ───────────────────── legacy paths stay byte-identical ─────────────────────
def test_ok_missing_and_flag_off_identical(run_state, monkeypatch, tmp_path):
    # knob off: the summary is never read — even a hollow run gets the legacy pack
    run_state("hollow")
    monkeypatch.setattr(Config, "REPORT_SIGNAL_PACK_HEALTH_GATE", False, raising=False)
    off = _agent()
    assert off._build_signal_pack() == _LEGACY_FULL
    assert off._signal_pack_health is None
    monkeypatch.setattr(Config, "REPORT_SIGNAL_PACK_HEALTH_GATE", True, raising=False)

    # healthy run
    run_state("ok")
    ok = _agent()
    assert ok._build_signal_pack() == _LEGACY_FULL
    assert ok._signal_pack_health == {"health": "ok", "suppressed": []}

    # summary without a health field (predates health accounting) / unreadable summaries
    for raw in (json.dumps({"simulation_id": SIM_ID}), "{not json", json.dumps(["hollow"]),
                json.dumps({"simulation_health": 7}), json.dumps({"simulation_health": " "})):
        run_state(raw=raw)
        agent = _agent()
        assert agent._build_signal_pack() == _LEGACY_FULL, raw
        assert agent._signal_pack_health["health"] is None, raw

    # missing summary
    os.remove(os.path.join(SimulationRunner.RUN_STATE_DIR, SIM_ID, "run_summary.json"))
    missing = _agent()
    assert missing._build_signal_pack() == _LEGACY_FULL
    assert missing._signal_pack_health == {"health": None, "suppressed": []}

    # an unsafe simulation id never reaches the filesystem and keeps the legacy pack
    escape = _agent()
    escape.simulation_id = "../" + SIM_ID
    assert escape._build_signal_pack() == _LEGACY_FULL
    assert escape._signal_pack_health == {"health": None, "suppressed": []}


# ─────────────── gate skipped / unrecognised values are visible ───────────────
@pytest.mark.parametrize("raw", ["{not json", json.dumps(["hollow"]),
                                 json.dumps({"simulation_health": 7}),
                                 json.dumps({"simulation_health": None}),
                                 json.dumps({"simulation_health": " "})])
def test_unreadable_summary_warns_and_is_flagged(run_state, warnings_log, raw):
    run_state(raw=raw)
    agent = _agent()

    # the pack stays the legacy one (spec: parse error -> health None) ...
    assert agent._build_signal_pack() == _LEGACY_FULL
    # ... but the skipped gate is flagged apart from an absent summary and logged at WARNING
    assert agent._signal_pack_health == {
        "health": None, "suppressed": [], "summary_unreadable": True}
    warned = _gate_warnings(warnings_log)
    assert len(warned) == 1 and "run_summary.json 存在但不可读" in warned[0]
    assert all(r.levelno == logging.WARNING for r in warnings_log)


def test_absent_summary_stays_silent(run_state, warnings_log):
    # no summary file, an unsafe id, and a summary that predates health accounting
    missing = _agent()
    assert missing._build_signal_pack() == _LEGACY_FULL
    escape = _agent()
    escape.simulation_id = "../" + SIM_ID
    assert escape._build_signal_pack() == _LEGACY_FULL
    run_state(raw=json.dumps({"simulation_id": SIM_ID, "organic_action_count": 12}))
    legacy = _agent()
    assert legacy._build_signal_pack() == _LEGACY_FULL

    for agent in (missing, escape, legacy):
        assert agent._signal_pack_health == {"health": None, "suppressed": []}
    assert _gate_warnings(warnings_log) == []


def test_unrecognised_health_leans_closed(run_state, warnings_log):
    run_state("Stalled")
    agent = _agent()

    pack = agent._build_signal_pack()

    caveat = _UNKNOWN.format(health="stalled")
    assert pack == _pack(_WORLD_STATE, _TIERS, _COALITIONS, _SPINE, _DIFF, note=caveat)
    assert pack != _LEGACY_FULL
    assert agent._signal_pack_health == {"health": "stalled", "suppressed": []}
    warned = _gate_warnings(warnings_log)
    assert len(warned) == 1 and "未识别的 simulation_health='stalled'" in warned[0]


def test_unrecognised_health_note_is_length_capped(run_state):
    run_state("x" * 500)
    agent = _agent()

    pack = agent._build_signal_pack()

    assert _UNKNOWN.format(health="x" * 40) in pack
    assert "x" * 41 not in pack
    assert agent._signal_pack_health["health"] == "x" * 500


@pytest.mark.parametrize("health", ["ok", "hollow", "errored", "truncated", "llm_degraded"])
def test_known_health_values_do_not_warn(run_state, warnings_log, health):
    run_state(health)
    _agent()._build_signal_pack()
    assert _gate_warnings(warnings_log) == []


def test_no_update_policy_still_suppresses_before_the_gate(run_state, monkeypatch):
    run_state("hollow")
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "no_update", raising=False)
    agent = _agent()

    assert agent._build_signal_pack() == ""
    assert agent._signal_pack_health is None
    assert agent.zep_tools.calls == []


# ───────────────────────────── forecast.json quality ─────────────────────────────
def _finalize_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    for knob in ("REPORT_FORECAST_SELF_CRITIQUE", "FORECAST_EMIT_BINARY", "REPORT_PUBLISH_GATE",
                 "REPORT_REPAIR_PASSES", "REPORT_FORECAST_LEDGER"):
        monkeypatch.setattr(Config, knob, False, raising=False)
    agent = _agent()
    defaults = {
        "llm": None, "simulation_requirement": "Will capacity expand by 2027?",
        "situation_brief": "", "sources": [], "research_report": "",
        "output_language": "English", "scenario_label": "", "_background_block": "",
        "_sources_index": "", "_signal_pack": "", "_market_pack": "",
        "_forecast_spine_block": "", "report_logger": None, "console_logger": None,
        "tools": {},
        "_forecast_spine": {"scenarios": [{"name": "Expand", "probability": 0.6},
                                          {"name": "Stall", "probability": 0.4}],
                            "critiqued": True, "confidence": "medium"},
    }
    for key, value in defaults.items():
        setattr(agent, key, value)
    return agent


def _finalize(agent, tmp_path, report_id):
    (tmp_path / "reports" / report_id).mkdir(parents=True)
    agent._finalize_structured_forecast(report_id, "# Title\n\nBody text without claims.")
    with open(tmp_path / "reports" / report_id / "forecast.json", encoding="utf-8") as fh:
        return json.load(fh)


def test_quality_record(run_state, monkeypatch, tmp_path):
    run_state("hollow")
    agent = _finalize_agent(tmp_path, monkeypatch)
    agent._signal_pack = agent._build_signal_pack()      # as generate_report does

    forecast = _finalize(agent, tmp_path, "report_r5_hollow")

    assert forecast["quality"]["signal_pack_health"] == {
        "health": "hollow", "suppressed": _ACTIVITY_SUPPRESSED}
    assert [s["name"] for s in forecast["scenarios"]] == ["Expand", "Stall"]


def test_quality_record_separates_unreadable_from_absent(run_state, monkeypatch, tmp_path):
    absent = _finalize_agent(tmp_path, monkeypatch)
    absent._signal_pack = absent._build_signal_pack()
    assert _finalize(absent, tmp_path, "report_r5_absent")["quality"]["signal_pack_health"] == {
        "health": None, "suppressed": []}

    run_state(raw="{not json")
    unreadable = _finalize_agent(tmp_path, monkeypatch)
    unreadable._signal_pack = unreadable._build_signal_pack()
    forecast = _finalize(unreadable, tmp_path, "report_r5_unreadable")
    assert forecast["quality"]["signal_pack_health"] == {
        "health": None, "suppressed": [], "summary_unreadable": True}


def test_quality_record_absent_when_gate_off_or_pack_never_built(run_state, monkeypatch, tmp_path):
    run_state("hollow")
    monkeypatch.setattr(Config, "REPORT_SIGNAL_PACK_HEALTH_GATE", False, raising=False)
    off = _finalize_agent(tmp_path, monkeypatch)
    off._signal_pack = off._build_signal_pack()
    assert off._signal_pack == _LEGACY_FULL
    assert "signal_pack_health" not in (_finalize(off, tmp_path, "report_r5_off").get("quality") or {})

    monkeypatch.setattr(Config, "REPORT_SIGNAL_PACK_HEALTH_GATE", True, raising=False)
    never_built = _finalize_agent(tmp_path, monkeypatch)
    assert "signal_pack_health" not in (
        _finalize(never_built, tmp_path, "report_r5_unbuilt").get("quality") or {})


# ───────────────────────────── knob wiring ─────────────────────────────
def test_knob_defaults_on_and_is_documented():
    assert Config.REPORT_SIGNAL_PACK_HEALTH_GATE is True
    with open(cfgmod.__file__, encoding="utf-8") as fh:
        src = fh.read()
    assert re.search(r"REPORT_SIGNAL_PACK_HEALTH_GATE = os\.environ\.get\(\s*"
                     r"'REPORT_SIGNAL_PACK_HEALTH_GATE', 'true'\)\.strip\(\)\.lower\(\) == 'true'",
                     src)
    env_example = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(cfgmod.__file__)))), ".env.example")
    with open(env_example, encoding="utf-8") as fh:
        assert re.search(r"^# REPORT_SIGNAL_PACK_HEALTH_GATE=true\s+# REPORT-5", fh.read(), re.M)




# ─────────────── FU-3: tools, outline and what-if baselines (REPORT-5 follow-up) ───────────────
_BASE_NOTE = ("⚠️ 基线模拟未产出可用的行为数据（simulation_health={health}）——本报告不做基线与情景的"
              "行为对比；正文不得引用任何基线 vs 情景的行为差值。")
_UNUSABLE = ["hollow", "errored"]
# Baseline summaries the gate leaves alone: healthy, partial, unrecognised, absent, unreadable.
_USABLE_BASELINES = ["ok", "truncated", "llm_degraded", "stalled", None, "{not json"]

# The outline sweep and what-if strings as rendered before FU-3 (copied from plan_outline):
# the golden legacy outline prompt is built from them, independently of the gate code path.
_LEGACY_OUTCOMES_SWEEP = (
    "【内部方法学材料——情景推演量化产出（仅供规划参考）】\n"
    "使用规则：仅据此判断哪些现实世界行为者/议题值得设立章节深挖；"
    "不得为推演本身单设章节，任何章节标题不得含"
    "『模拟/Agent/智能体/行为轨迹/Simulation/Behavior』等方法学词汇。\n")
_LEGACY_DIFF_HEAD = "【基线 vs 情景 结构化对比（必须据此撰写对比章节）】\n"
_LEGACY_DIFF_MANDATE = (
    "\n\n**强制要求**：本报告为情景（What-If）预测，大纲必须包含一节标题含"
    "「情景对比」或「反事实」的章节，对比基线与本情景的关键差异（引用上面对比数据中的具体差值）。")
_NO_DIFF_MANDATE = (
    "\n\n**强制要求**：本报告为情景（What-If）预测，大纲必须包含一节标题含"
    "「情景对比」或「反事实」的章节，说明基线与本情景之间没有可用的行为对比数据，"
    "只依据研究材料讨论两者的差异。")
_TABLE_HEAD = "**基线 vs 情景 结构化对比（确定性聚合，权威）**"


def _write_summary(simulation_id, health):
    """Baseline (or any) run summary: a health value, None = no summary, '{…' = raw text."""
    sim_dir = Path(SimulationRunner.RUN_STATE_DIR) / simulation_id
    sim_dir.mkdir(exist_ok=True)
    path = sim_dir / "run_summary.json"
    if health is None:
        if path.exists():
            path.unlink()
        return
    text = health if health.startswith("{") else json.dumps(
        {"simulation_id": simulation_id, "simulation_health": health})
    path.write_text(text, encoding="utf-8")


# ───────────── signal pack: the baseline's diff block ─────────────
@pytest.mark.parametrize("base_health", _UNUSABLE)
def test_unusable_baseline_never_reaches_the_signal_pack(run_state, base_health):
    run_state("ok")
    _write_summary(BASE_SIM_ID, base_health)
    agent = _agent()

    pack = agent._build_signal_pack()

    assert pack == _pack(_WORLD_STATE, _TIERS, _COALITIONS, _SPINE, _BASE_NOTE.format(health=base_health))
    assert _DIFF not in pack
    assert agent.zep_tools.calls == ["simulation_outcomes", "coalition_map"]
    # the run's own verdict is untouched; the baseline's verdict is its own record
    assert agent._signal_pack_health == {"health": "ok", "suppressed": []}
    assert agent._baseline_health_record()["health"] == base_health


def test_usable_baseline_keeps_the_legacy_pack(run_state, monkeypatch):
    run_state("ok")
    for base_health in _USABLE_BASELINES:
        _write_summary(BASE_SIM_ID, base_health)
        assert (Path(SimulationRunner.RUN_STATE_DIR) / BASE_SIM_ID / "run_summary.json").exists() \
            is (base_health is not None)
        agent = _agent()
        assert agent._build_signal_pack() == _LEGACY_FULL, base_health
        assert agent._signal_pack_health == {"health": "ok", "suppressed": []}, base_health
        assert agent.zep_tools.calls == ["simulation_outcomes", "coalition_map", "scenario_diff"]
    _write_summary(BASE_SIM_ID, "errored")
    monkeypatch.setattr(Config, "REPORT_SIGNAL_PACK_HEALTH_GATE", False, raising=False)
    assert _agent()._build_signal_pack() == _LEGACY_FULL


# ───────────────────────────── ReACT tools ─────────────────────────────
class _FactionZep(_StubZep):
    """Runs the real ZepToolsService.faction_brief (its coalition_map fallback included)."""

    faction_brief = ZepToolsService.faction_brief

    def _inter_community_tension(self, graph_id, communities):
        return []


class _FakeRuntime:
    def __init__(self, communities):
        self._communities = communities

    def list_communities(self, graph_id):
        return list(self._communities)


_COMMUNITY = {"name": "晶圆联盟", "summary": "图谱社区摘要", "members": ["Orion Foundry"]}


def _tool_agent(**kw):
    agent = _agent(**kw)
    agent.simulation_requirement = "q"
    return agent


_ACTIVITY_TOOLS = ["simulation_outcomes", "coalition_map", "opinion_shift", "scenario_diff"]
_LEGACY_TOOL_OUTPUT = {"simulation_outcomes": _OUTCOMES, "coalition_map": _COALITIONS,
                       "opinion_shift": _SHIFT, "scenario_diff": _DIFF}


@pytest.mark.parametrize("health", _UNUSABLE)
@pytest.mark.parametrize("tool", _ACTIVITY_TOOLS)
def test_tools_return_the_no_behaviour_line_on_an_unusable_run(run_state, tool, health):
    run_state(health)
    _write_summary(BASE_SIM_ID, "hollow")      # the run's own line wins over the baseline's
    agent = _tool_agent()
    assert agent._execute_tool(tool, {"actor_name": "Orion Foundry"}) == _NO_BEHAVIOUR.format(health=health)
    assert agent.zep_tools.calls == []


@pytest.mark.parametrize("own_health", [None, "ok", "truncated", "stalled", "{not json"])
def test_tools_byte_identical_on_a_usable_run_and_with_the_knob_off(run_state, monkeypatch, own_health):
    if own_health is None:
        os.makedirs(os.path.join(SimulationRunner.RUN_STATE_DIR, SIM_ID), exist_ok=True)
    elif own_health.startswith("{"):
        run_state(raw=own_health)
    else:
        run_state(own_health)
    for tool in _ACTIVITY_TOOLS:
        agent = _tool_agent()
        assert agent._execute_tool(tool, {"actor_name": "Orion Foundry"}) == _LEGACY_TOOL_OUTPUT[tool]
        assert agent.zep_tools.calls == [tool]
    # knob off: legacy even on a hollow run with an errored baseline
    run_state("hollow")
    _write_summary(BASE_SIM_ID, "errored")
    monkeypatch.setattr(Config, "REPORT_SIGNAL_PACK_HEALTH_GATE", False, raising=False)
    for tool in _ACTIVITY_TOOLS:
        agent = _tool_agent()
        assert agent._execute_tool(tool, {"actor_name": "Orion Foundry"}) == _LEGACY_TOOL_OUTPUT[tool]
        assert agent.zep_tools.calls == [tool]


@pytest.mark.parametrize("base_health", _UNUSABLE)
def test_scenario_diff_tool_gives_the_baseline_line_for_an_unusable_baseline(run_state, base_health):
    run_state("ok")
    _write_summary(BASE_SIM_ID, base_health)
    agent = _tool_agent()
    assert agent._execute_tool("scenario_diff", {}) == _BASE_NOTE.format(health=base_health)
    assert agent.zep_tools.calls == []
    # the run's own behaviour tools do not depend on the baseline
    assert agent._execute_tool("simulation_outcomes", {}) == _OUTCOMES


def test_scenario_diff_tool_unchanged_for_a_usable_baseline(run_state):
    run_state("ok")
    for base_health in _USABLE_BASELINES:
        _write_summary(BASE_SIM_ID, base_health)
        agent = _tool_agent()
        assert agent._execute_tool("scenario_diff", {}) == _DIFF, base_health
    assert _tool_agent(base=None)._execute_tool("scenario_diff", {}) == "（本报告非情景对比报告，无基线模拟可对比）"


@pytest.mark.parametrize("health", _UNUSABLE)
def test_faction_brief_cannot_fall_back_to_coalition_map_on_an_unusable_run(run_state, monkeypatch, health):
    run_state(health)
    # retrieval off, or on with no community nodes: the fallback would be coalition_map
    for retrieval, communities in ((False, []), (True, [])):
        monkeypatch.setattr(Config, "GRAPH_COMMUNITY_RETRIEVAL", retrieval, raising=False)
        monkeypatch.setattr(rt_mod, "get_runtime", lambda c=communities: _FakeRuntime(c))
        agent = _tool_agent()
        agent.zep_tools = _FactionZep()
        assert agent._execute_tool("faction_brief", {}) == _NO_BEHAVIOUR.format(health=health)
        assert agent.zep_tools.calls == []
    # graph-native communities do not depend on simulation behaviour: still given
    monkeypatch.setattr(rt_mod, "get_runtime", lambda: _FakeRuntime([_COMMUNITY]))
    agent = _tool_agent()
    agent.zep_tools = _FactionZep()
    brief = agent._execute_tool("faction_brief", {})
    assert "晶圆联盟" in brief and "图谱社区摘要" in brief and _COALITIONS not in brief
    assert agent.zep_tools.calls == []


def test_faction_brief_unchanged_on_a_usable_run_and_with_the_knob_off(run_state, monkeypatch):
    monkeypatch.setattr(Config, "GRAPH_COMMUNITY_RETRIEVAL", False, raising=False)
    run_state("ok")
    agent = _tool_agent()
    agent.zep_tools = _FactionZep()
    assert agent._execute_tool("faction_brief", {}) == _COALITIONS
    assert agent.zep_tools.calls == ["coalition_map"]
    run_state("hollow")
    monkeypatch.setattr(Config, "REPORT_SIGNAL_PACK_HEALTH_GATE", False, raising=False)
    agent = _tool_agent()
    agent.zep_tools = _FactionZep()
    assert agent._execute_tool("faction_brief", {}) == _COALITIONS


# ───────────────────── one health verdict per simulation ─────────────────────
def test_each_summary_is_read_once_per_report(run_state, monkeypatch, warnings_log):
    run_state(raw="{not json")
    _write_summary(BASE_SIM_ID, "{not json")
    reads = []
    real_read = ReportAgent._read_run_summary_health
    monkeypatch.setattr(ReportAgent, "_read_run_summary_health",
                        lambda self, sid: reads.append(sid) or real_read(self, sid))
    agent = _tool_agent()

    agent._build_signal_pack()
    for _ in range(2):
        for tool in _ACTIVITY_TOOLS:
            agent._execute_tool(tool, {"actor_name": "Orion Foundry"})
    agent._scenario_diff_structured()
    agent._baseline_health_record()

    assert sorted(reads) == sorted([SIM_ID, BASE_SIM_ID])
    # one WARNING per unreadable summary, not one per consumer
    warned = _gate_warnings(warnings_log)
    assert len(warned) == 2 and all("run_summary.json 存在但不可读" in w for w in warned)
    # every consumer shares the first verdict for the rest of the report
    run_state("hollow")
    assert agent._execute_tool("simulation_outcomes", {}) == _OUTCOMES


# ───────────────────────────── plan_outline ─────────────────────────────
class _OutlineLLM:
    def __init__(self):
        self.user_prompt = None

    def chat_json(self, messages=None, temperature=0.3, **kw):
        self.user_prompt = messages[-1]["content"]
        return {"title": "T", "summary": "S",
                "sections": [{"title": f"章节{i}", "description": ""} for i in range(5)]}


class _OutlineZep(_StubZep):
    def get_simulation_context(self, graph_id=None, simulation_requirement=None, **kw):
        return {"graph_statistics": {}, "total_entities": 0, "related_facts": []}

    def insight_forge(self, **kw):
        raise RuntimeError("no forge in test")


def _outline_agent(base=BASE_SIM_ID, *, with_pack=False):
    agent = _agent(base=base)
    agent.simulation_requirement = "q"
    agent.actors = None
    agent.sources = []
    agent._background_block = agent._sources_index = agent._forecast_spine_block = ""
    agent.zep_tools = _OutlineZep()
    agent._signal_pack = agent._build_signal_pack() if with_pack else ""
    agent.zep_tools.calls.clear()
    agent.llm = _OutlineLLM()
    return agent


def _outline_prompt(base=BASE_SIM_ID, *, with_pack=False):
    agent = _outline_agent(base, with_pack=with_pack)
    agent.plan_outline()
    return agent.llm.user_prompt, agent.zep_tools.calls, agent


def _outline_head(agent):
    """The outline prompt up to the simulation sweeps (code FU-3 does not touch)."""
    return agent._prepend_research_background(PLAN_USER_PROMPT_TEMPLATE.format(
        simulation_requirement="q", total_nodes=0, total_edges=0, entity_types=[],
        total_entities=0, related_facts_json=json.dumps([], ensure_ascii=False, indent=2)))


def _legacy_outline(agent):
    """Golden outline prompt as plan_outline built it before FU-3."""
    prompt = _outline_head(agent) + "\n\n" + _LEGACY_OUTCOMES_SWEEP + _OUTCOMES
    if agent.base_simulation_id:
        prompt += "\n\n" + _LEGACY_DIFF_HEAD + _DIFF + _LEGACY_DIFF_MANDATE
    return prompt


@pytest.mark.parametrize("base", [BASE_SIM_ID, None])
@pytest.mark.parametrize("own_health", [None, "ok", "truncated", "llm_degraded", "stalled", "{not json"])
def test_outline_byte_identical_for_a_usable_run(run_state, own_health, base):
    if own_health is None:
        os.makedirs(os.path.join(SimulationRunner.RUN_STATE_DIR, SIM_ID), exist_ok=True)
    elif own_health.startswith("{"):
        run_state(raw=own_health)
    else:
        run_state(own_health)
    _write_summary(BASE_SIM_ID, "ok")
    prompt, calls, agent = _outline_prompt(base)
    assert prompt == _legacy_outline(agent)
    assert calls == (["simulation_outcomes", "scenario_diff"] if base else ["simulation_outcomes"])


@pytest.mark.parametrize("base_health", _USABLE_BASELINES)
def test_outline_byte_identical_for_a_usable_baseline(run_state, base_health):
    run_state("ok")
    _write_summary(BASE_SIM_ID, base_health)
    prompt, calls, agent = _outline_prompt()
    assert prompt == _legacy_outline(agent)
    assert calls == ["simulation_outcomes", "scenario_diff"]


@pytest.mark.parametrize("with_pack", [False, True])
def test_outline_byte_identical_with_the_knob_off(run_state, monkeypatch, with_pack):
    run_state("hollow")
    _write_summary(BASE_SIM_ID, "errored")
    monkeypatch.setattr(Config, "REPORT_SIGNAL_PACK_HEALTH_GATE", False, raising=False)
    prompt, calls, agent = _outline_prompt(with_pack=with_pack)
    assert prompt == _legacy_outline(agent)
    assert calls == ["simulation_outcomes", "scenario_diff"]
    assert agent._baseline_health_record() is None


@pytest.mark.parametrize("health", _UNUSABLE)
def test_outline_gets_no_seed_echo_data_from_an_unusable_run(run_state, health):
    run_state(health)
    note = _NO_BEHAVIOUR.format(health=health)
    # what-if report: the line once, then the comparison mandate without cited deltas
    prompt, calls, agent = _outline_prompt()
    assert prompt == _outline_head(agent) + "\n\n" + note + _NO_DIFF_MANDATE
    assert calls == []
    # plain report: just the line
    prompt, calls, agent = _outline_prompt(base=None)
    assert prompt == _outline_head(agent) + "\n\n" + note
    assert calls == []
    # the pinned signal pack already carries the line: it is not repeated
    _write_summary(BASE_SIM_ID, "hollow")
    prompt, calls, agent = _outline_prompt(with_pack=True)
    assert note in agent._signal_pack
    assert prompt == _outline_head(agent) + _NO_DIFF_MANDATE
    assert prompt.count(note) == 1 and _BASE_NOTE.format(health="hollow") not in prompt
    assert "Orion Foundry" not in prompt.replace(agent._signal_pack, "") and _DIFF not in prompt
    assert calls == []


@pytest.mark.parametrize("base_health", _UNUSABLE)
def test_outline_gated_on_an_unusable_baseline(run_state, base_health):
    run_state("ok")
    _write_summary(BASE_SIM_ID, base_health)
    note = _BASE_NOTE.format(health=base_health)
    prompt, calls, agent = _outline_prompt()
    assert prompt == (_outline_head(agent) + "\n\n" + _LEGACY_OUTCOMES_SWEEP + _OUTCOMES
                      + "\n\n" + note + _NO_DIFF_MANDATE)
    assert calls == ["simulation_outcomes"]
    # with the pinned signal pack (which carries the baseline line) the line is not repeated
    prompt, calls, agent = _outline_prompt(with_pack=True)
    assert note in agent._signal_pack
    assert prompt == (_outline_head(agent) + "\n\n" + _LEGACY_OUTCOMES_SWEEP + _OUTCOMES
                      + _NO_DIFF_MANDATE)
    assert prompt.count(note) == 1 and _DIFF not in prompt
    assert calls == ["simulation_outcomes"]


# ───────────────────────────── comparison table ─────────────────────────────
@pytest.fixture
def table_data(run_state, monkeypatch, tmp_path):
    """Valid world-state trajectories on both sides and a tmp reports dir."""
    data = tmp_path / "sims"
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(data), raising=False)
    monkeypatch.setattr(Config, "REPORT_WORLDSTATE_HIDE_INVALID", True, raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    for sid, share in ((SIM_ID, 0.6), (BASE_SIM_ID, 0.4)):
        (data / sid).mkdir(parents=True)
        (data / sid / "world_state_trajectory.json").write_text(json.dumps(
            {"outcome": {"shares": {"A": share, "B": 1 - share}}, "validity": "valid"}), encoding="utf-8")
    return tmp_path / "reports"


def _table_agent():
    agent = _agent()
    agent.scenario_label = "what-if"
    return agent


@pytest.mark.parametrize("own_health,base_health", [(h, "ok") for h in _UNUSABLE]
                         + [("ok", h) for h in _UNUSABLE])
def test_no_comparison_table_when_either_side_is_unusable(run_state, table_data, own_health, base_health):
    run_state(own_health)
    _write_summary(BASE_SIM_ID, base_health)
    assert _table_agent()._scenario_diff_structured() is None


def test_comparison_table_unchanged_for_usable_runs_and_with_the_knob_off(run_state, table_data,
                                                                           monkeypatch):
    run_state("ok")
    _write_summary(BASE_SIM_ID, "ok")
    healthy = _table_agent()._scenario_diff_structured()
    assert healthy and [d["name"] for d in healthy["dimensions"]]
    for base_health in _USABLE_BASELINES:
        _write_summary(BASE_SIM_ID, base_health)
        assert _table_agent()._scenario_diff_structured() == healthy, base_health
    run_state("hollow")
    _write_summary(BASE_SIM_ID, "errored")
    monkeypatch.setattr(Config, "REPORT_SIGNAL_PACK_HEALTH_GATE", False, raising=False)
    assert _table_agent()._scenario_diff_structured() == healthy


def test_comparison_chapter_gets_the_line_instead_of_the_table(run_state, table_data, monkeypatch):
    body = "正文：两种情景的差异只依据研究材料讨论。"
    run_state("ok")
    _write_summary(BASE_SIM_ID, "ok")
    out = _table_agent()._prepend_comparison_table("r_fu3_ok", body)
    assert out.startswith(_TABLE_HEAD) and out.endswith("\n\n" + body)
    assert (table_data / "r_fu3_ok" / "comparison.json").exists()

    # hollow baseline + healthy fork: the baseline line in the table's place, no comparison.json
    _write_summary(BASE_SIM_ID, "hollow")
    assert (_table_agent()._prepend_comparison_table("r_fu3_base", body)
            == _BASE_NOTE.format(health="hollow") + "\n\n" + body)
    assert not (table_data / "r_fu3_base").exists()

    # the run itself unusable: REPORT-5's line (it wins over the baseline's)
    run_state("errored")
    assert (_table_agent()._prepend_comparison_table("r_fu3_own", body)
            == _NO_BEHAVIOUR.format(health="errored") + "\n\n" + body)
    assert not (table_data / "r_fu3_own").exists()

    # no table for another reason (missing trajectory): the chapter stays as it was
    run_state("ok")
    _write_summary(BASE_SIM_ID, "ok")
    os.remove(os.path.join(Config.OASIS_SIMULATION_DATA_DIR, BASE_SIM_ID, "world_state_trajectory.json"))
    assert _table_agent()._prepend_comparison_table("r_fu3_missing", body) == body


# ───────────────────── baseline verdict in forecast.json quality ─────────────────────
def _finalize_quality(tmp_path, monkeypatch, report_id, *, base=BASE_SIM_ID):
    agent = _finalize_agent(tmp_path, monkeypatch)
    agent.base_simulation_id = base
    agent._signal_pack = agent._build_signal_pack()      # as generate_report does
    return _finalize(agent, tmp_path, report_id).get("quality") or {}


@pytest.mark.parametrize("base_health", _UNUSABLE)
def test_baseline_verdict_is_persisted_next_to_signal_pack_health(run_state, monkeypatch, tmp_path,
                                                                  base_health):
    monkeypatch.setattr(Config, "REPORT_COMPARISON_TABLE", True, raising=False)
    run_state("ok")
    _write_summary(BASE_SIM_ID, base_health)
    quality = _finalize_quality(tmp_path, monkeypatch, f"r_fu3_{base_health}")
    assert quality["signal_pack_health"] == {"health": "ok", "suppressed": []}
    assert quality["baseline_signal_pack_health"] == {
        "health": base_health, "suppressed": ["scenario_diff", "comparison_table"]}

    # recorded whatever the run's own health (both sides unusable)
    run_state("hollow")
    quality = _finalize_quality(tmp_path, monkeypatch, f"r_fu3_both_{base_health}")
    assert quality["signal_pack_health"] == {"health": "hollow", "suppressed": _ACTIVITY_SUPPRESSED}
    assert quality["baseline_signal_pack_health"]["health"] == base_health

    # the comparison table off: only the diff consumers are listed
    monkeypatch.setattr(Config, "REPORT_COMPARISON_TABLE", False, raising=False)
    quality = _finalize_quality(tmp_path, monkeypatch, f"r_fu3_notable_{base_health}")
    assert quality["baseline_signal_pack_health"] == {"health": base_health, "suppressed": ["scenario_diff"]}


def test_unreadable_baseline_summary_is_flagged(run_state, monkeypatch, tmp_path):
    run_state("ok")
    _write_summary(BASE_SIM_ID, "{not json")
    quality = _finalize_quality(tmp_path, monkeypatch, "r_fu3_unreadable")
    assert quality["baseline_signal_pack_health"] == {
        "health": None, "suppressed": [], "summary_unreadable": True}


def test_no_baseline_verdict_for_usable_baselines_plain_reports_or_the_knob_off(run_state, monkeypatch,
                                                                                tmp_path):
    run_state("ok")
    for base_health in ("ok", "truncated", "llm_degraded", "stalled", None):
        _write_summary(BASE_SIM_ID, base_health)
        quality = _finalize_quality(tmp_path, monkeypatch, f"r_fu3_usable_{base_health}")
        assert "baseline_signal_pack_health" not in quality, base_health
        assert quality["signal_pack_health"] == {"health": "ok", "suppressed": []}
    _write_summary(BASE_SIM_ID, "hollow")
    assert "baseline_signal_pack_health" not in _finalize_quality(
        tmp_path, monkeypatch, "r_fu3_plain", base=None)
    monkeypatch.setattr(Config, "REPORT_SIGNAL_PACK_HEALTH_GATE", False, raising=False)
    quality = _finalize_quality(tmp_path, monkeypatch, "r_fu3_off")
    assert "baseline_signal_pack_health" not in quality and "signal_pack_health" not in quality
