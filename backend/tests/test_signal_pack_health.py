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
- ok, a missing or unreadable summary, or the knob off: the legacy pack,
  byte-identical.

The verdict is kept on the agent and written to forecast.json as
quality.signal_pack_health. Offline: tmp run-state dir, stub tools, no LLM.
"""

import json
import os
import re

import pytest

import app.config as cfgmod
from app.config import Config
from app.services.report_agent import ReportAgent, ReportManager, salience_tiers_from_outcomes
from app.services.simulation_runner import SimulationRunner

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

_NO_BEHAVIOUR = ("⚠️ 本次模拟未产出可用的行为数据（simulation_health={health}）——这不是「行为者无反应」"
                 "的发现；正文不得引用任何基于模拟行为量或派系聚类的推演结论。")
_PARTIAL = ("⚠️ 模拟运行状态：{health}（未完整或降级完成）——以下诊断材料只覆盖部分运行，"
            "引用须更加审慎。")

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

    # unreadable summary / summary without a health field / unknown health value
    for raw in ("{not json", json.dumps({"simulation_id": SIM_ID}), json.dumps(["hollow"]),
                json.dumps({"simulation_health": 7}),
                json.dumps({"simulation_health": "some_future_state"})):
        run_state(raw=raw)
        agent = _agent()
        assert agent._build_signal_pack() == _LEGACY_FULL, raw

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
