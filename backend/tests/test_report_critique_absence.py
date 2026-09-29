"""REPORT-4 (B): the section critique never shows an absent slot as a finding.

Recording LLM over ``ReportAgent._critique_section_draft``: no spine => no
probability-consistency rule and no spine slot; absent signal pack / market table
=> typed markers plus the '[S#]' carve-out; first section => an explicit
first-section note and no no-repeat rule; the concurrent outline brief is labelled
as such; the literal '（无）' never appears with REPORT_ABSENCE_MARKERS on, and
REPORT_ABSENCE_MARKERS=False reproduces the legacy prompts byte for byte.
"""

from __future__ import annotations

import itertools

import pytest

from app.config import Config
from app.services.report_agent import ReportAgent, ReportSection
from app.utils import absence


class _RecLLM:
    def __init__(self, responses=("PASS",)):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages=None, **kw):
        self.calls.append({"messages": messages, **kw})
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


def _agent(**over):
    a = ReportAgent.__new__(ReportAgent)
    a.sources = []
    a.research_report = ""
    a.situation_brief = ""
    a._background_block = ""
    a._outline_summary = ""
    a.output_language = "English"
    a._forecast_spine = None
    a._forecast_spine_block = ""
    a._signal_pack = ""
    a._market_pack = ""
    for k, v in over.items():
        setattr(a, k, v)
    return a


_SPINE = {"scenarios": [{"name": "Base", "probability": 0.6},
                        {"name": "Alt", "probability": 0.4}]}
_SPINE_TXT = "Base: 60%；Alt: 40%"
_SIGNAL = "## 模拟量化结果\n- Top actor A"
_MARKET = "| Optimus milestone by 2026 | implied YES 12.5% |"
_PRIOR = ["## Earlier section\n\nEarlier body text."]
_SECTION = ReportSection(title="Body 1", description="")
_DRAFT = "x" * 120


def _critique(agent, previous=()):
    agent._critique_section_draft(_SECTION, _DRAFT, list(previous))
    msgs = agent.llm.calls[-1]["messages"]
    return msgs[0]["content"], msgs[1]["content"]


def _legacy_prompts(agent, *, spine_txt, signal_txt, market_txt, prior):
    """The pre-REPORT-4 critique prompts, spelled out literally."""
    floor = agent._section_char_floor()
    lang = agent.output_language
    sys_prompt = (
        "你是一名严格的报告章节质检员。仅依据下方给定材料，判断本章草稿是否同时满足四条标准：\n"
        "1) 概率一致性：正文若提及情景/事件概率，须与【预测骨架概率】一致，不得矛盾；\n"
        "2) 硬数字接地：关于现实世界的关键定量声明必须带来源标注 [S#]；【信号包】中的数字"
        "是内部模拟推演产物（elicited model projection），只有在正文显式标注其模拟来源时"
        "才可引用，绝不能替代 [S#] 作为现实世界声明的接地；【预测市场表】中的隐含概率/"
        "价格是机器抓取的真实市场数据（Polymarket 公开 API），正文引用且与表内数值一致时"
        "视为已接地，不要求 [S#]，绝不能当作捏造数字要求删除或改写；\n"
        f"3) 篇幅下限：正文须有不少于 {floor} 字符的实质内容；\n"
        "4) 不复述前序章节：不得大段重复【前序章节摘要】中的内容。\n"
        f"全部满足 ⇒ 只输出 PASS（不要任何多余文字）；否则 ⇒ 只输出一条最关键、可执行、"
        f"具体的修订指令（用{lang}书写，单句，不要解释）。"
    )
    usr_prompt = (
        f"【预测骨架概率】\n{spine_txt or '（无）'}\n\n"
        f"【信号包（硬数字）】\n{signal_txt or '（无）'}\n\n"
        f"【预测市场表】\n{market_txt or '（无）'}\n\n"
        f"【前序章节摘要】\n{prior or '（无）'}\n\n"
        f"【本章标题】{_SECTION.title}\n\n"
        f"【本章草稿】\n{_DRAFT}"
    )
    return sys_prompt, usr_prompt


def test_no_spine_drops_probability_rule_and_slot():
    a = _agent(llm=_RecLLM(), _signal_pack=_SIGNAL, _market_pack=_MARKET)
    sys_p, usr_p = _critique(a, _PRIOR)
    assert "概率一致性" not in sys_p and "【预测骨架概率】" not in sys_p
    assert "【预测骨架概率】" not in usr_p
    assert sys_p.startswith("你是一名严格的报告章节质检员。仅依据下方给定材料，判断本章草稿是否同时满足三条标准：\n1) 硬数字接地")
    assert "3) 不复述前序章节：不得大段重复【前序章节摘要】中的内容。\n" in sys_p


def test_spine_present_keeps_probability_rule():
    a = _agent(llm=_RecLLM(), _forecast_spine=_SPINE)
    sys_p, usr_p = _critique(a, _PRIOR)
    assert "1) 概率一致性：正文若提及情景/事件概率，须与【预测骨架概率】一致，不得矛盾；" in sys_p
    assert usr_p.startswith(f"【预测骨架概率】\n{_SPINE_TXT}\n\n")


def test_missing_market_pack_gets_typed_marker_and_s_carveout():
    # conftest disables PREDICTION_MARKETS_ENABLED → the market step is not part of the run.
    a = _agent(llm=_RecLLM())
    sys_p, usr_p = _critique(a, _PRIOR)
    marker = absence.absence_marker("预测市场表", absence.not_run("prediction_markets_disabled"))
    assert f"【预测市场表】\n{marker}\n\n" in usr_p
    assert ("本次运行无可用的预测市场表：正文中未带 [S#] 的预测市场价格/隐含概率没有机器证据，"
            "按未接地处理（带 [S#] 的研究材料数字不受影响）") in sys_p
    assert "机器抓取的真实市场数据" not in sys_p


def test_missing_market_pack_with_markets_enabled_is_unavailable(monkeypatch):
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)
    a = _agent(llm=_RecLLM(), _market_status=absence.unavailable("partial_transport_failure"))
    _, usr_p = _critique(a, _PRIOR)
    assert "（预测市场表：本次运行中不可用（partial_transport_failure）——不是空结果" in usr_p
    b = _agent(llm=_RecLLM(), _market_status=absence.empty("no_equivalent_market"))
    _, usr_b = _critique(b, _PRIOR)
    assert "（预测市场表：已执行检索但未找到可用结果（no_equivalent_market）" in usr_b
    # A status recorded as present while no table reached the prompt is not a present slot.
    c = _agent(llm=_RecLLM(), _market_status=absence.present("research_snapshot"))
    _, usr_c = _critique(c, _PRIOR)
    assert "本次运行中不可用（market_pack_empty）" in usr_c


def test_present_market_table_passes_through_byte_identically():
    a = _agent(llm=_RecLLM(), _market_pack=_MARKET)
    sys_p, usr_p = _critique(a, _PRIOR)
    assert f"【预测市场表】\n{_MARKET}\n\n" in usr_p
    assert ("【预测市场表】中的隐含概率/价格是机器抓取的真实市场数据（Polymarket 公开 API），"
            "正文引用且与表内数值一致时视为已接地，不要求 [S#]，绝不能当作捏造数字要求删除或改写") in sys_p


def test_missing_signal_pack_marker_and_clause(monkeypatch):
    a = _agent(llm=_RecLLM(), _market_pack=_MARKET)
    sys_p, usr_p = _critique(a, _PRIOR)
    assert ("本次质检未注入内部情景推演诊断材料：任何「内部情景推演显示…」类论断视为无依据"
            in sys_p)
    assert "【信号包】中的数字是内部模拟推演产物" not in sys_p
    assert "（信号包：本次运行未启用该步骤——不是空结果，不可据此推断任何结论）" in usr_p
    assert "signal_pack_not_injected" not in usr_p  # not_run markers carry no reason text
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "no_update", raising=False)
    b = _agent(llm=_RecLLM(), _market_pack=_MARKET)
    _, usr_b = _critique(b, _PRIOR)
    assert "（信号包：本次运行未启用该步骤" in usr_b


def test_signal_pack_present_passes_through():
    a = _agent(llm=_RecLLM(), _signal_pack=_SIGNAL, _market_pack=_MARKET)
    sys_p, usr_p = _critique(a, _PRIOR)
    assert f"【信号包（硬数字）】\n{_SIGNAL}\n\n" in usr_p
    assert "【信号包】中的数字是内部模拟推演产物（elicited model projection）" in sys_p


def test_first_section_has_no_repeat_rule():
    a = _agent(llm=_RecLLM(), _forecast_spine=_SPINE, _market_pack=_MARKET)
    sys_p, usr_p = _critique(a, [])
    assert "【前序章节摘要】\n（尚无前序章节：这是第一个章节）\n\n" in usr_p
    assert "不复述前序章节" not in sys_p and "大段重复" not in sys_p
    assert "三条标准" in sys_p
    assert "3) 篇幅下限：" in sys_p and sys_p.split("3) 篇幅下限：", 1)[1].split("\n", 1)[0].endswith("。")


def test_concurrent_outline_brief_is_labelled_as_such():
    brief = ReportAgent._build_synthesis_brief([
        ReportSection(title="Body 1", description="drivers"),
        ReportSection(title="Body 2", description="risks"),
    ])
    a = _agent(llm=_RecLLM(), _market_pack=_MARKET)
    sys_p, usr_p = _critique(a, [brief])
    assert "【报告大纲意图（并行撰写，前序正文不可用）】\n" + brief in usr_p
    assert "【前序章节摘要】" not in usr_p and "【前序章节摘要】" not in sys_p
    assert "不与其他章节的既定意图大段重复" in sys_p


@pytest.mark.parametrize("spine,signal,market,previous", list(itertools.product(
    (None, _SPINE), ("", _SIGNAL), ("", _MARKET), ([], _PRIOR))))
def test_no_none_literal_with_knob_on(spine, signal, market, previous):
    a = _agent(llm=_RecLLM(), _forecast_spine=spine, _signal_pack=signal, _market_pack=market)
    sys_p, usr_p = _critique(a, previous)
    assert "（无）" not in sys_p and "（无）" not in usr_p


def test_knob_on_with_every_slot_present_matches_legacy():
    a = _agent(llm=_RecLLM(), _forecast_spine=_SPINE, _signal_pack=_SIGNAL, _market_pack=_MARKET)
    got = _critique(a, _PRIOR)
    assert got == _legacy_prompts(a, spine_txt=_SPINE_TXT, signal_txt=_SIGNAL,
                                  market_txt=_MARKET, prior=_PRIOR[0])


@pytest.mark.parametrize("spine,signal,market,previous", [
    (None, "", "", []),
    (_SPINE, _SIGNAL, _MARKET, _PRIOR),
    (None, _SIGNAL, "", _PRIOR),
])
def test_knob_off_reproduces_legacy_prompts(monkeypatch, spine, signal, market, previous):
    monkeypatch.setattr(Config, "REPORT_ABSENCE_MARKERS", False, raising=False)
    a = _agent(llm=_RecLLM(), _forecast_spine=spine, _signal_pack=signal, _market_pack=market)
    got = _critique(a, previous)
    spine_txt = _SPINE_TXT if spine else ""
    assert got == _legacy_prompts(a, spine_txt=spine_txt, signal_txt=signal,
                                  market_txt=market, prior=previous[0] if previous else "")


def test_pass_fail_parsing_unchanged():
    a = _agent(llm=_RecLLM(["PASS"]))
    assert a._critique_section_draft(_SECTION, _DRAFT, []) is None
    b = _agent(llm=_RecLLM(["FAIL"]))
    assert b._critique_section_draft(_SECTION, _DRAFT, []) is None
    c = _agent(llm=_RecLLM(["补充 [S2] 来源"]))
    assert c._critique_section_draft(_SECTION, _DRAFT, []) == "补充 [S2] 来源"
