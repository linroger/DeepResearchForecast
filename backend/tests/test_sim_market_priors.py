"""ITEM 11 — 市场先验注入（SIM_MARKET_PRIORS）。

Offline: no LLM/network. Covers:
- simulation_config_generator：市场定价块拼装（top 5 / relevance+volume 排序 / 无效行剔除）；
  world_brief 注入（开关开+非空市场→present；开关关/空市场→absent）；handoff 载入
  （fake handoff dir → 命中；缺 simulation_id / 开关关 / 文件缺失 → []）。
- oasis_profile_generator：市场感知提示（分析师/媒体角色+话题重叠→'markets ... at NN%'；
  非该类角色 / 无重叠 / 无市场 / 开关关 → ""）；_generate_profile_with_llm 提示词注入的角色门控。
- TIME-3 endDate gate: expired (or research-stamped) markets never reach the world brief
  or persona hints under PREDICTION_MARKETS_END_DATE_GATE; with the gate off they are kept.
"""

import json
import os
import sys
from datetime import datetime, timezone

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.config import Config  # noqa: E402
from app.services import pipeline_orchestrator as po  # noqa: E402
from app.services.oasis_profile_generator import OasisProfileGenerator  # noqa: E402
from app.services.simulation_config_generator import SimulationConfigGenerator  # noqa: E402
from app.utils import prediction_markets as pm  # noqa: E402


# --------------------------------------------------------------------------- fixtures
# relevance-gated 市场快照（handoff/prediction_markets.json 的 markets[] schema 子集）。
MARKETS = [
    {"question": "Will the US relax AI chip export controls to China by end of 2026?",
     "implied_yes_prob": 0.34, "relevance_score": 9.0, "volume": 120000.0},
    {"question": "Will Nvidia H20 shipments to China resume in 2026?",
     "implied_yes_prob": 0.58, "relevance_score": 8.0, "volume": 90000.0},
    {"question": "Will there be a new semiconductor tariff announced in 2026?",
     "implied_yes_prob": 0.21, "relevance_score": 7.0, "volume": 50000.0},
    {"question": "Will TSMC build a second Arizona fab by 2027?",
     "implied_yes_prob": 0.65, "relevance_score": 6.0, "volume": 30000.0},
    {"question": "Will China restrict rare-earth exports in 2026?",
     "implied_yes_prob": 0.44, "relevance_score": 5.0, "volume": 20000.0},
    {"question": "Will a low-relevance market appear here at 2028?",
     "implied_yes_prob": 0.5, "relevance_score": 1.0, "volume": 10000.0},
]

QUESTION = "2026年底前美国是否会放宽对华AI芯片出口管制？请评估各情景概率。"


def _config_gen() -> SimulationConfigGenerator:
    return SimulationConfigGenerator.__new__(SimulationConfigGenerator)


def _profile_gen() -> OasisProfileGenerator:
    return OasisProfileGenerator.__new__(OasisProfileGenerator)


# ===========================================================================
# Part 1 — 市场定价块（_build_market_pricing_block）
# ===========================================================================

def test_market_block_top_n_and_pct_rendered():
    block = _config_gen()._build_market_pricing_block(MARKETS)
    assert "市场定价" in block
    # top N = 5：应含头 5 条（relevance 9→5），不含 relevance=1 的第 6 条
    assert "34%" in block and "58%" in block and "21%" in block
    assert "export controls to China" in block
    assert "low-relevance market" not in block  # 第 6 条被 top-5 截断
    assert block.count("\n- ") == 5 and block.startswith("## 市场定价")  # 5 行市场（各占一行）


def test_market_block_sorted_by_relevance_then_volume():
    block = _config_gen()._build_market_pricing_block(MARKETS)
    lines = [l for l in block.split("\n") if l.startswith("- ")]
    # 第一行应是 relevance 最高（9.0）的出口管制市场
    assert "export controls to China" in lines[0] and "34%" in lines[0]


def test_market_block_skips_invalid_rows_and_empty():
    assert _config_gen()._build_market_pricing_block([]) == ""
    assert _config_gen()._build_market_pricing_block(None) == ""
    bad = [{"question": "", "implied_yes_prob": 0.5},
           {"question": "no prob here"},
           {"question": "bool prob", "implied_yes_prob": True}]
    assert _config_gen()._build_market_pricing_block(bad) == ""


# ===========================================================================
# Part 2 — world_brief 注入（_build_world_brief）
# ===========================================================================

def test_world_brief_includes_market_block_when_enabled(monkeypatch):
    monkeypatch.setattr(Config, "SIM_WORLD_BRIEF", True, raising=False)
    monkeypatch.setattr(Config, "SIM_MARKET_PRIORS", True, raising=False)
    brief = _config_gen()._build_world_brief(
        QUESTION, None, ["AI芯片出口管制"], prediction_markets=MARKETS)
    assert "市场定价" in brief
    assert "34%" in brief


def test_world_brief_omits_market_block_when_flag_off(monkeypatch):
    monkeypatch.setattr(Config, "SIM_WORLD_BRIEF", True, raising=False)
    monkeypatch.setattr(Config, "SIM_MARKET_PRIORS", "false", raising=False)
    brief = _config_gen()._build_world_brief(
        QUESTION, None, ["AI芯片出口管制"], prediction_markets=MARKETS)
    assert "市场定价" not in brief
    assert QUESTION[:20] in brief  # 其余段落不受影响


def test_world_brief_omits_market_block_when_no_markets(monkeypatch):
    monkeypatch.setattr(Config, "SIM_WORLD_BRIEF", True, raising=False)
    monkeypatch.setattr(Config, "SIM_MARKET_PRIORS", True, raising=False)
    brief = _config_gen()._build_world_brief(QUESTION, None, ["话题"], prediction_markets=[])
    assert "市场定价" not in brief
    # 缺省参数（旧调用方，不传 prediction_markets）也不注入 —— 逐字节旧行为
    brief_legacy = _config_gen()._build_world_brief(QUESTION, None, ["话题"])
    assert "市场定价" not in brief_legacy


# ===========================================================================
# Part 3 — handoff 载入（_load_prediction_markets）
# ===========================================================================

def _fake_handoff(monkeypatch, tmp_path, payload, *, sim_id="sim1"):
    """把 payload 写入 tmp_path/prediction_markets.json，并把 PipelineManager 指向它。"""
    if payload is not None:
        with open(os.path.join(tmp_path, "prediction_markets.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f)
    monkeypatch.setattr(po.PipelineManager, "list_pipelines",
                        classmethod(lambda cls: [{"pipeline_id": "p1"}]), raising=False)
    monkeypatch.setattr(
        po.PipelineManager, "load",
        classmethod(lambda cls, pid: {"simulation_id": sim_id, "graph_id": "g1",
                                      "handoff_dir": str(tmp_path)}),
        raising=False)


def test_load_prediction_markets_from_handoff(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "SIM_MARKET_PRIORS", True, raising=False)
    _fake_handoff(monkeypatch, tmp_path, {"markets": MARKETS})
    rows = _config_gen()._load_prediction_markets("sim1")
    assert len(rows) == len(MARKETS)
    assert rows[0]["implied_yes_prob"] == 0.34


def test_load_prediction_markets_no_sim_id_or_flag_off(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "SIM_MARKET_PRIORS", True, raising=False)
    _fake_handoff(monkeypatch, tmp_path, {"markets": MARKETS})
    assert _config_gen()._load_prediction_markets(None) == []
    assert _config_gen()._load_prediction_markets("") == []
    # 开关关闭 → []（即便 handoff 有文件）
    monkeypatch.setattr(Config, "SIM_MARKET_PRIORS", "false", raising=False)
    assert _config_gen()._load_prediction_markets("sim1") == []


def test_load_prediction_markets_missing_file_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "SIM_MARKET_PRIORS", True, raising=False)
    _fake_handoff(monkeypatch, tmp_path, None)  # 不写文件
    assert _config_gen()._load_prediction_markets("sim1") == []
    # sim_id 不匹配任何管线 → []
    _fake_handoff(monkeypatch, tmp_path, {"markets": MARKETS}, sim_id="other")
    assert _config_gen()._load_prediction_markets("sim1") == []


# ===========================================================================
# Part 4 — 人设市场感知提示（_market_awareness_hint）
# ===========================================================================

def test_market_hint_for_analyst_role_with_overlap(monkeypatch):
    monkeypatch.setattr(Config, "SIM_MARKET_PRIORS", True, raising=False)
    gen = _profile_gen()
    gen._prediction_markets = lambda: MARKETS  # 绕过 handoff 载入
    hint = gen._market_awareness_hint(
        "Jane Analyst", "Journalist",
        "Covers semiconductor export controls and China chip policy.", actor=None)
    assert "市场先验感知" in hint
    assert "%" in hint
    # 应命中重叠最强的出口管制市场（export/controls/china/semiconductor 多词重叠）
    assert "export controls" in hint and "34%" in hint


def test_market_hint_role_gated_non_analyst(monkeypatch):
    monkeypatch.setattr(Config, "SIM_MARKET_PRIORS", True, raising=False)
    gen = _profile_gen()
    gen._prediction_markets = lambda: MARKETS
    # Government / Company 不是分析师/媒体角色 → 无提示
    for etype in ("Government", "Company", "Person", "University"):
        assert gen._market_awareness_hint(
            "US Commerce", etype,
            "Semiconductor export controls China policy.", actor=None) == ""


def test_market_hint_no_overlap_returns_empty(monkeypatch):
    monkeypatch.setattr(Config, "SIM_MARKET_PRIORS", True, raising=False)
    gen = _profile_gen()
    gen._prediction_markets = lambda: MARKETS
    # 分析师角色但话题完全不搭（园艺）→ 无重叠 → 无提示
    assert gen._market_awareness_hint(
        "Garden Weekly", "MediaOutlet",
        "Coverage of tomatoes, roses and backyard composting.", actor=None) == ""


def test_market_hint_flag_off_and_no_markets(monkeypatch):
    gen = _profile_gen()
    gen._prediction_markets = lambda: MARKETS
    monkeypatch.setattr(Config, "SIM_MARKET_PRIORS", "false", raising=False)
    assert gen._market_awareness_hint(
        "Jane", "Journalist", "semiconductor export controls china", actor=None) == ""
    # 开关开但无市场 → 无提示
    monkeypatch.setattr(Config, "SIM_MARKET_PRIORS", True, raising=False)
    gen2 = _profile_gen()
    gen2._prediction_markets = lambda: []
    assert gen2._market_awareness_hint(
        "Jane", "Journalist", "semiconductor export controls china", actor=None) == ""


def test_prediction_markets_no_graph_id_returns_empty(monkeypatch):
    """无 graph_id（__new__ 实例）→ [] 且不触碰 PipelineManager。"""
    monkeypatch.setattr(Config, "SIM_MARKET_PRIORS", True, raising=False)
    gen = _profile_gen()
    assert gen._prediction_markets() == []


# ===========================================================================
# Part 5 — 提示词注入的角色门控（_generate_profile_with_llm）
# ===========================================================================

class _StubLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def chat(self, messages=None, **kwargs):
        self.calls.append(messages)
        return json.dumps(self.payload, ensure_ascii=False)

    def last_user_prompt(self):
        return self.calls[-1][-1]["content"]


_PAYLOAD = {"bio": "b", "persona": "p"}


def _run(entity_type, monkeypatch, markets=MARKETS):
    monkeypatch.setattr(Config, "SIM_MARKET_PRIORS", True, raising=False)
    gen = _profile_gen()
    gen.llm = _StubLLM(_PAYLOAD)
    gen._prediction_markets = lambda: markets
    gen._generate_profile_with_llm(
        entity_name="Analyst Desk", entity_type=entity_type,
        entity_summary="Semiconductor export controls and China chip policy analysis.",
        entity_attributes={}, context="", actor=None, actors=None)
    return gen.llm.last_user_prompt()


def test_prompt_injects_hint_for_media_role(monkeypatch):
    prompt = _run("Journalist", monkeypatch)
    assert "市场先验感知" in prompt and "34%" in prompt


def test_prompt_no_hint_for_non_media_role(monkeypatch):
    prompt = _run("Company", monkeypatch)
    assert "市场先验感知" not in prompt


# ===========================================================================
# Part 6 — TIME-3 endDate gate (PREDICTION_MARKETS_END_DATE_GATE)
# ===========================================================================
# An expired-but-open ladder child (endDate passed, still priced at 3% while it awaits
# settlement) must never seed SIM priors under the gate; with the gate off it is kept.
# The clock is pinned (market_clock_now) so these tests never depend on the wall clock.
_TIME3_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
_EXPIRED = {"market_id": "A",
            "question": "Will the US relax AI chip export controls to China by September 2026?",
            "implied_yes_prob": 0.03, "relevance_score": 9.5, "volume": 150000.0,
            "end_date": "2026-09-30T00:00:00Z"}
_LIVE = dict(MARKETS[1], market_id="B", end_date="2027-03-31T00:00:00Z")


@pytest.fixture
def end_date_gate(monkeypatch):
    """Pin the market clock and enable SIM priors; returns a gate on/off setter."""
    monkeypatch.setattr(pm, "market_clock_now", lambda: _TIME3_NOW)
    monkeypatch.setattr(Config, "SIM_WORLD_BRIEF", True, raising=False)
    monkeypatch.setattr(Config, "SIM_MARKET_PRIORS", True, raising=False)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GRACE_HOURS", 0.0, raising=False)

    def _set(enabled):
        monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GATE", enabled, raising=False)
    _set(True)
    return _set


def _profile_gen_for_graph() -> OasisProfileGenerator:
    gen = _profile_gen()
    gen.graph_id = "g1"  # _fake_handoff's pipeline carries graph_id g1
    return gen


def test_end_date_gate_drops_expired_rows_from_world_brief(monkeypatch, tmp_path, end_date_gate):
    _fake_handoff(monkeypatch, tmp_path, {"markets": [_EXPIRED, _LIVE]})
    rows = _config_gen()._load_prediction_markets("sim1")
    assert [m["market_id"] for m in rows] == ["B"]
    brief = _config_gen()._build_world_brief(
        QUESTION, None, ["AI芯片出口管制"], prediction_markets=rows)
    assert "市场定价" in brief and "58%" in brief
    assert "by September 2026" not in brief and "3%" not in brief


def test_end_date_gate_all_expired_leaves_no_world_brief_block(monkeypatch, tmp_path,
                                                              end_date_gate):
    # A row stamped upstream by the research snapshot is dropped even if its end_date
    # would not have passed yet at the pinned clock.
    stamped = dict(_LIVE, window_ended=True)
    _fake_handoff(monkeypatch, tmp_path, {"markets": [_EXPIRED, stamped]})
    rows = _config_gen()._load_prediction_markets("sim1")
    assert rows == []
    brief = _config_gen()._build_world_brief(
        QUESTION, None, ["AI芯片出口管制"], prediction_markets=rows)
    assert "市场定价" not in brief


def test_end_date_gate_off_keeps_expired_rows_in_world_brief(monkeypatch, tmp_path,
                                                            end_date_gate):
    end_date_gate(False)
    _fake_handoff(monkeypatch, tmp_path, {"markets": [_EXPIRED, _LIVE]})
    rows = _config_gen()._load_prediction_markets("sim1")
    assert rows == [_EXPIRED, _LIVE]  # the pre-gate rows, unchanged
    brief = _config_gen()._build_world_brief(
        QUESTION, None, ["AI芯片出口管制"], prediction_markets=rows)
    assert "by September 2026" in brief and "3%" in brief


def test_end_date_gate_drops_expired_rows_from_persona_hint(monkeypatch, tmp_path,
                                                           end_date_gate):
    _fake_handoff(monkeypatch, tmp_path, {"markets": [_EXPIRED]})
    gen = _profile_gen_for_graph()
    assert gen._prediction_markets() == []
    assert gen._market_awareness_hint(
        "Jane Analyst", "Journalist",
        "Covers semiconductor export controls and China chip policy.", actor=None) == ""


def test_end_date_gate_off_keeps_expired_rows_in_persona_hint(monkeypatch, tmp_path,
                                                             end_date_gate):
    end_date_gate(False)
    _fake_handoff(monkeypatch, tmp_path, {"markets": [_EXPIRED]})
    gen = _profile_gen_for_graph()
    assert gen._prediction_markets() == [_EXPIRED]
    hint = gen._market_awareness_hint(
        "Jane Analyst", "Journalist",
        "Covers semiconductor export controls and China chip policy.", actor=None)
    assert "by September 2026" in hint and "3%" in hint
