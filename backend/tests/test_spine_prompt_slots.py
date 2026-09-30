"""REPORT-4 (D): the forecast-spine prompt names only the inputs it actually carries.

Under the default SIMULATION_FORECAST_EFFECT=diagnostic_only the report never passes
a signal pack to derive_forecast_spine, yet the legacy lead sentence named
【模拟量化信号】.  With REPORT_ABSENCE_MARKERS on, the lead lists the appended blocks,
the research-input label lists the forecast_inputs sections present, and a missing
research base rate asks for a numeric outside-view anchor labelled as model judgment.
"""

from __future__ import annotations

import hashlib

from app.config import Config
from app.services import forecast_extractor as fe
from app.services.forecast_extractor import derive_forecast_spine
from app.utils import actors as actors_mod

from tests.conftest import FakeLLMClient

_SCEN = {
    "headline": "h", "horizon": "2027",
    "scenarios": [
        {"name": "A", "probability": 0.6, "summary": "s", "key_drivers": [],
         "resolution_criteria": "x > 1 by 2027"},
        {"name": "B", "probability": 0.4, "summary": "s", "key_drivers": [],
         "resolution_criteria": "x <= 1 by 2027"},
    ],
    "confidence": "medium",
}
_NO_BASE_RATE_NOTE = ("（研究输入未提供参考类基率：各情景 base_rate_anchor 仍须给出数值化的外部视角基率，"
                      "但须写明其为模型外部视角判断、非研究来源；不得虚构来源或出处。）")


def _prompt(**kwargs) -> str:
    fake = FakeLLMClient(json_responses=[dict(_SCEN) for _ in range(4)])
    out = derive_forecast_spine(fake, **kwargs)
    assert out["scenarios"]
    return fake.calls[0]["messages"][0]["content"]


def _actors(**fi):
    return {"forecast_inputs": fi}


_FULL_INPUTS = actors_mod.forecast_inputs_block(_actors(
    base_rates=[{"reference_class": "tariff rounds", "outcome_frequency": "30%"}],
    drivers=[{"variable": "inflation", "direction": "up"}],
    indicators=[{"indicator": "CPI", "date_or_trigger": "2027-01"}],
    scenarios=[{"name": "base", "probability_band": "40-60%", "narrative": "n"}],
))
_SCENARIO_ONLY = actors_mod.forecast_inputs_block(_actors(
    scenarios=[{"name": "base", "probability_band": "40-60%", "narrative": "n"}]))


def test_split_reconstructs_legacy_instructions():
    assert fe._SPINE_LEAD_LEGACY + fe._SPINE_BODY == fe._SPINE_INSTRUCTIONS
    assert fe._SPINE_BODY.startswith("\n只输出 JSON")


def test_diagnostic_only_prompt_never_names_simulation_signal():
    p = _prompt(central_question="q", horizon="2030", forecast_inputs=_FULL_INPUTS,
                signal_pack="")
    assert "模拟量化信号" not in p
    assert p.startswith("你是预测校准专家。在撰写任何叙事之前，先基于下面提供的输入"
                        "（核心问题、预测时间范围、研究输入），给出一个**机器可读**的结构化预测骨架。"
                        "\n只输出 JSON")
    # Every research section present -> the legacy label, and no base-rate provenance note.
    assert "\n\n[研究输入：参考类基率 / 驱动因素 / 观察指标 / 候选情景]\n" in p
    assert _NO_BASE_RATE_NOTE not in p


def test_scenario_only_inputs_label_and_base_rate_provenance():
    p = _prompt(central_question="q", forecast_inputs=_SCENARIO_ONLY)
    assert "\n\n[研究输入：候选情景]\n" in p
    assert fe._SPINE_BODY + "\n" + _NO_BASE_RATE_NOTE + "\n\n[核心问题]\nq" in p


def test_unrecognised_inputs_get_plain_label():
    p = _prompt(forecast_inputs="free-form research notes")
    assert "\n\n[研究输入]\nfree-form research notes" in p
    assert "（研究输入）" in p and _NO_BASE_RATE_NOTE in p


def test_lead_lists_every_block_actually_appended(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SPINE_ANCHOR_WORLDSTATE", True, raising=False)
    p = _prompt(central_question="q", horizon="2030", situation_brief="brief",
                forecast_inputs=_FULL_INPUTS, signal_pack="SIG", market_block="| m | 30% |",
                quantitative_facts="GDP 2%", base_distribution={"A": 0.6, "B": 0.4})
    assert p.startswith(
        "你是预测校准专家。在撰写任何叙事之前，先基于下面提供的输入（核心问题、预测时间范围、态势简报、"
        "研究输入、模拟量化信号、预测市场隐含概率、S级量化事实、基准分布锚点），"
        "给出一个**机器可读**的结构化预测骨架。")
    assert "\n\n[模拟量化信号]\nSIG" in p  # legacy_prompt path still carries the block


def test_quantitative_facts_suppress_the_model_judgment_note():
    # The S-grade facts block asks base_rate_anchor to cite its indicator + as_of date;
    # telling the model to label the anchor as unsourced model judgment would contradict it.
    p = _prompt(central_question="q", forecast_inputs=_SCENARIO_ONLY,
                quantitative_facts="GDP growth 2.1% (as_of 2026-06)")
    assert "\n\n[S级量化事实（数字底座，base_rate_anchor 须引用其中的 指标+as_of 日期）]\n" in p
    assert _NO_BASE_RATE_NOTE not in p and "模型外部视角判断" not in p


def test_base_distribution_suppresses_the_model_judgment_note(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SPINE_ANCHOR_WORLDSTATE", True, raising=False)
    p = _prompt(central_question="q", base_distribution={"A": 0.6, "B": 0.4})
    assert "\n\n[基准分布锚点（模拟 WorldState 份额，先验）]\n" in p
    assert _NO_BASE_RATE_NOTE not in p


def test_market_block_alone_keeps_the_model_judgment_note():
    p = _prompt(central_question="q", forecast_inputs=_SCENARIO_ONLY, market_block="| m | 30% |")
    assert _NO_BASE_RATE_NOTE in p


def test_no_blocks_lead():
    p = _prompt()
    assert p.startswith("你是预测校准专家。在撰写任何叙事之前，给出一个**机器可读**的结构化预测骨架。"
                        "\n只输出 JSON")
    assert "预测市场隐含概率" not in p and "模拟量化信号" not in p
    assert p.endswith(_NO_BASE_RATE_NOTE)


def _legacy_prompt(*, central_question="", horizon="", situation_brief="", forecast_inputs="",
                   signal_pack="", market_block=""):
    """The pre-REPORT-4 concatenation, spelled out from the unchanged instructions."""
    user = fe._SPINE_INSTRUCTIONS
    if central_question:
        user += f"\n\n[核心问题]\n{central_question}"
    if horizon:
        user += f"\n\n[预测时间范围]\n{horizon}"
    if situation_brief:
        user += f"\n\n[态势简报]\n{situation_brief}"
    if forecast_inputs:
        user += f"\n\n[研究输入：参考类基率 / 驱动因素 / 观察指标 / 候选情景]\n{forecast_inputs}"
    if signal_pack:
        user += f"\n\n[模拟量化信号]\n{signal_pack}"
    if market_block:
        user += ("\n\n[预测市场隐含概率（Polymarket 实盘·校准锚点，非真值）]\n" + market_block
                 + "\n与上述市场重叠的情景，其概率须对照市场隐含概率；偏离超过 10 个百分点时"
                   "在 adjustment_rationale 中显式解释分歧（市场遗漏/错价了什么）。")
    return user


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_knob_off_prompt_sha_equals_legacy(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_ABSENCE_MARKERS", False, raising=False)
    cases = [
        {},
        {"central_question": "q", "forecast_inputs": _SCENARIO_ONLY},
        {"central_question": "q", "horizon": "2030", "situation_brief": "b",
         "forecast_inputs": _FULL_INPUTS, "signal_pack": "SIG", "market_block": "| m | 30% |"},
    ]
    for kwargs in cases:
        assert _sha(_prompt(**kwargs)) == _sha(_legacy_prompt(**kwargs))


def test_report_agent_spine_prompt_under_diagnostic_only(tmp_path, monkeypatch):
    """End to end through ReportAgent: the default policy never hands the spine a signal
    pack, so the prompt neither names nor carries 【模拟量化信号】."""
    from app.services.report_agent import ReportAgent, ReportManager

    monkeypatch.setattr(ReportManager, "_get_report_folder",
                        classmethod(lambda cls, rid: str(tmp_path)), raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_SELF_CRITIQUE", False, raising=False)
    fake = FakeLLMClient(json_responses=[dict(_SCEN) for _ in range(4)])
    a = ReportAgent.__new__(ReportAgent)
    a.llm = fake
    a.actors = _actors(scenarios=[{"name": "base", "probability_band": "40-60%"}])
    a.simulation_requirement = "Will X happen by 2030?"
    a.situation_brief = ""
    a._signal_pack = "## 模拟量化结果\n- Top actor A"
    a._market_pack = ""
    a._forecast_spine = None
    a._forecast_spine_block = ""
    a._temporal_horizon_date = lambda: ""
    a._derive_and_pin_forecast_spine("r1")
    prompt = fake.calls[0]["messages"][0]["content"]
    assert "模拟量化信号" not in prompt and "Top actor A" not in prompt
    assert "[研究输入：候选情景]" in prompt and _NO_BASE_RATE_NOTE in prompt
