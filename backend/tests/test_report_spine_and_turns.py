"""Offline tests for the report bucket spine/turn-budget changes.

Covers, with no LLM/network (stubbed deps):
  * R2-KG-7  _build_causal_spine_block (chokepoint neighborhoods + source→outcome path)
  * R2-DETAIL-2 plan_outline forecast-spine + required-structure injection (and no-op default)
  * REPORT-9  per-turn max_tokens (tool-turn budget below MIN, full SECTION budget at/after MIN)
  * REPORT-10 ReAct temperature reads Config.REPORT_AGENT_TEMPERATURE
  * REPORT-8  interview_agents excluded from the unused-tools nudge set
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services.report_agent import (  # noqa: E402
    ReportAgent, ReportOutline, ReportSection,
)


# ───────────────────────────────── R2-KG-7 ──────────────────────────────────
class _CascadeZT:
    """Stub zep_tools recording trace_cascade calls; returns plausible renders."""

    def __init__(self, degraded=False):
        self.calls = []
        self.degraded = degraded

    def trace_cascade(self, graph_id, source="", target="", center="", causal_only=True):
        self.calls.append({"graph_id": graph_id, "source": source,
                            "target": target, "center": center})
        if self.degraded:
            return "（图谱遍历失败）"
        if center:
            return f"【{center} 的多跳传导邻域（2 条边）】\n· {center} --[CAUSES]--> X"
        if source and target:
            return f"【传导路径：{source} → {target}】\n· (1跳) {source} --[CAUSES]--> {target}"
        return "（trace_cascade 需要 source+target 或 center）"


def _causal_agent(actors, zt):
    a = ReportAgent.__new__(ReportAgent)
    a.graph_id = "g1"
    a.actors = actors
    a.zep_tools = zt
    return a


def test_causal_spine_block_renders_chokepoints_and_path():
    zt = _CascadeZT()
    actors = {"actors": [
        {"name": "Alpha", "salience": {"score": 0.9}},
        {"name": "Beta", "salience": {"score": 0.6}},
    ]}
    block = _causal_agent(actors, zt)._build_causal_spine_block()
    assert "因果骨架" in block            # header present
    assert "Alpha" in block               # top chokepoint neighborhood
    assert "Beta" in block                # source→outcome path target
    # two center sweeps (Alpha, Beta) + one source→target path (Alpha→Beta)
    centers = [c for c in zt.calls if c["center"]]
    paths = [c for c in zt.calls if c["source"] and c["target"]]
    assert {c["center"] for c in centers} == {"Alpha", "Beta"}
    assert paths and paths[0]["source"] == "Alpha" and paths[0]["target"] == "Beta"


def test_causal_spine_block_ranks_by_salience():
    """Highest-salience actor is the primary chokepoint (path source)."""
    zt = _CascadeZT()
    actors = {"actors": [
        {"name": "Low", "salience": {"score": 0.3}},
        {"name": "High", "salience": {"score": 0.95}},
    ]}
    _causal_agent(actors, zt)._build_causal_spine_block()
    paths = [c for c in zt.calls if c["source"] and c["target"]]
    assert paths and paths[0]["source"] == "High"


def test_causal_spine_block_degrades_to_empty():
    # No actors → no chokepoints → "".
    assert _causal_agent(None, _CascadeZT())._build_causal_spine_block() == ""
    # All traversals degraded → filtered out → "".
    actors = {"actors": [{"name": "Alpha"}, {"name": "Beta"}]}
    assert _causal_agent(actors, _CascadeZT(degraded=True))._build_causal_spine_block() == ""


# ─────────────────────────────── R2-DETAIL-2 ────────────────────────────────
class _PlanZT:
    def get_simulation_context(self, graph_id=None, simulation_requirement=None):
        return {"graph_statistics": {}, "total_entities": 0, "related_facts": []}

    def insight_forge(self, **kw):
        raise RuntimeError("no forge in test")  # caught + ignored

    def simulation_outcomes(self, simulation_id, top_n=10):
        return ""  # falsy → skipped


class _PlanLLM:
    def __init__(self):
        self.user_prompt = None

    def chat_json(self, messages=None, temperature=0.3, **kw):
        self.user_prompt = messages[-1]["content"]
        return {"title": "T", "summary": "S",
                "sections": [{"title": f"S{i}", "description": ""} for i in range(5)]}


def _plan_agent():
    a = ReportAgent.__new__(ReportAgent)
    a.graph_id = "g1"
    a.simulation_id = "sim1"
    a.simulation_requirement = "会发生什么？"
    a.base_simulation_id = None
    a.situation_brief = ""
    a.actors = None
    a.sources = []
    a._background_block = ""
    a._sources_index = ""
    a._forecast_spine_block = ""
    a._signal_pack = ""
    a.zep_tools = _PlanZT()
    a.llm = _PlanLLM()
    return a


def test_plan_outline_injects_spine_and_required_structure():
    a = _plan_agent()
    outline = a.plan_outline(
        forecast_spine_block="SPINE_BLOCK_XYZ",
        require_forecast_structure=True,
    )
    assert isinstance(outline, ReportOutline)
    assert "SPINE_BLOCK_XYZ" in a.llm.user_prompt
    assert "结构强制要求（预测优先）" in a.llm.user_prompt


def test_plan_outline_default_is_noop():
    a = _plan_agent()
    a.plan_outline()  # defaults: no spine block, no forced structure
    assert "SPINE_BLOCK_XYZ" not in a.llm.user_prompt
    assert "结构强制要求（预测优先）" not in a.llm.user_prompt


# ───────────────────────── REPORT-8 / REPORT-9 / REPORT-10 ───────────────────
class _ReactLLM:
    """Scripted ReAct LLM recording temperature + max_tokens per chat() call."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self._i = 0

    def chat(self, messages=None, temperature=0.3, max_tokens=4096, **kw):
        self.calls.append({"temperature": temperature, "max_tokens": max_tokens,
                            "messages": [dict(m) for m in messages]})
        r = self.responses[min(self._i, len(self.responses) - 1)]
        self._i += 1
        return r


def _react_agent(responses):
    a = ReportAgent.__new__(ReportAgent)
    a.simulation_requirement = "会发生什么？"
    a.base_simulation_id = None
    a.report_logger = None
    a.tools = {}
    a.sources = []
    a._background_block = ""
    a._sources_index = ""
    a._forecast_spine_block = ""
    a._signal_pack = ""
    a._section_tool_calls = 0
    # keep the loop short: 1 tool call satisfies MIN, 2 is the ceiling
    a.MIN_TOOL_CALLS_PER_SECTION = 1
    a.MAX_TOOL_CALLS_PER_SECTION = 2
    a.llm = _ReactLLM(responses)
    a._execute_tool = lambda name, params, report_context="": "RESULT-DATA"
    return a


def _run_react(a):
    section = ReportSection(title="正文1", description="")
    outline = ReportOutline(title="T", summary="S", sections=[section])
    # RQ-1: 正文须 >= MIN_VALID_SECTION_CHARS(800)，否则会被判无效而重试/落占位符。
    body = "这是一段足够长的中文正文内容。" * 60
    return a._generate_section_react(section, outline, previous_sections=[]), body


def test_react_turn_budgets_and_temperature():
    body = "这是一段足够长的中文正文内容。" * 60  # RQ-1: >= 800 字符
    a = _react_agent([
        '<tool_call>\n{"name": "insight_forge", "parameters": {"query": "q"}}\n</tool_call>',
        "Final Answer: " + body,
    ])
    result, _ = _run_react(a)
    assert body in result
    assert len(a.llm.calls) == 2
    # REPORT-10: every ReAct turn uses the configured temperature (not hardcoded 0.5).
    for c in a.llm.calls:
        assert c["temperature"] == Config.REPORT_AGENT_TEMPERATURE
    # REPORT-9: turn-1 (below MIN) uses the small tool-turn budget; turn-2 (at MIN, can
    # emit the final answer) uses the full section budget.
    tool_turn = getattr(Config, "REPORT_AGENT_TOOL_TURN_MAX_TOKENS", 8192)
    assert a.llm.calls[0]["max_tokens"] == tool_turn
    assert a.llm.calls[1]["max_tokens"] == Config.REPORT_AGENT_SECTION_MAX_TOKENS


def test_react_unused_hint_excludes_interview_agents():
    """REPORT-8: the 'tools you haven't used' nudge must never recommend interview_agents."""
    body = "这是一段足够长的中文正文内容。" * 60  # RQ-1: >= MIN_VALID_SECTION_CHARS(800)
    a = _react_agent([
        '<tool_call>\n{"name": "insight_forge", "parameters": {"query": "q"}}\n</tool_call>',
        "Final Answer: " + body,
    ])
    a.tools = {name: {"name": name, "description": "Read research", "parameters": {}}
               for name in ("insight_forge", "quick_search")}
    _run_react(a)
    # The observation after the first tool call carries the unused-tools hint.
    # LOOP-015: the nudge text changed from "你还没有使用过" to a relevance-gated hint;
    # match on the new constant's distinctive phrasing.
    hint_msgs = [
        m["content"] for call in a.llm.calls for m in call["messages"]
        if isinstance(m.get("content"), str) and "可补充视角的未用工具" in m["content"]
    ]
    assert hint_msgs, "expected an unused-tools nudge to be emitted"
    for msg in hint_msgs:
        assert "interview_agents" not in msg
        assert "quick_search" in msg
        assert not any(name in msg for name in ("simulation_outcomes", "coalition_map", "opinion_shift"))


# ─────────────────────────── RQ-1: report shape helper ──────────────────────
from app.services.report_agent import (  # noqa: E402
    derive_report_shape, MIN_VALID_SECTION_CHARS, _looks_contaminated, ReportManager,
)


def test_derive_report_shape_no_budget_is_expanded():
    """无 page_budget → 展开默认（6-14 节 / 2000 下限 / 3000-6000 目标 / 12 工具）。"""
    s = derive_report_shape(None)
    assert s == {"min_sections": 6, "max_sections": 14, "floor_chars": 2000,
                 "target_lo": 3000, "target_hi": 6000, "tool_budget": 12}


def test_derive_report_shape_small_budget_is_compact():
    """小 page_budget（<=8 页）→ 紧凑（5-8 节 / 1500 下限 / 1800-2800 目标 / 8 工具）。"""
    for pb in (1, 4, 8):
        s = derive_report_shape(pb)
        assert s == {"min_sections": 5, "max_sections": 8, "floor_chars": 1500,
                     "target_lo": 1800, "target_hi": 2800, "tool_budget": 8}


def test_derive_report_shape_large_budget_is_expanded():
    """大 page_budget（>8 页）→ 展开默认。"""
    assert derive_report_shape(20)["max_sections"] == 14
    assert derive_report_shape(9)["tool_budget"] == 12


def test_derive_report_shape_bad_or_zero_budget_falls_back_expanded():
    """非法/<=0 的 page_budget 视作「无预算」→ 展开（degrade-safe）。"""
    assert derive_report_shape(0)["min_sections"] == 6
    assert derive_report_shape(-3)["min_sections"] == 6
    assert derive_report_shape("garbage")["min_sections"] == 6


def test_derive_report_shape_honours_expanded_overrides():
    """展开默认由调用方注入（Config 单一真源），本函数保持纯净。"""
    s = derive_report_shape(None, expanded_min_sections=7, expanded_max_sections=12,
                            expanded_floor_chars=2500, expanded_target_lo=3500,
                            expanded_target_hi=7000, expanded_tool_budget=10)
    assert s == {"min_sections": 7, "max_sections": 12, "floor_chars": 2500,
                 "target_lo": 3500, "target_hi": 7000, "tool_budget": 10}


def _shape_agent(requirement=""):
    a = ReportAgent.__new__(ReportAgent)
    a.simulation_requirement = requirement
    a.research_report = ""
    a._report_shape_cache = None
    a.MIN_TOOL_CALLS_PER_SECTION = ReportAgent.MIN_TOOL_CALLS_PER_SECTION
    a.MAX_TOOL_CALLS_PER_SECTION = ReportAgent.MAX_TOOL_CALLS_PER_SECTION
    return a


def test_report_shape_expands_without_page_budget():
    """需求书无页数预算 → _report_shape 展开（6-14 节）。"""
    a = _shape_agent("What will happen to the market next year?")
    shape = a._report_shape()
    assert shape["min_sections"] == 6 and shape["max_sections"] == 14
    assert shape["target_hi"] == 6000


def test_report_shape_compacts_on_small_page_budget():
    """需求书要求 <=6 页 → _report_shape 收敛回紧凑（5-8 节 / 1800-2800 目标 / 8 工具）。"""
    a = _shape_agent("Please keep the submission to 6 pages or less.")
    shape = a._report_shape()
    assert shape["min_sections"] == 5 and shape["max_sections"] == 8
    assert shape["target_lo"] == 1800 and shape["target_hi"] == 2800
    assert shape["tool_budget"] == 8
    # 提示词槽位随形状收敛
    kw = a._section_prompt_kwargs()
    assert kw["section_target_lo"] == 1800 and kw["section_target_hi"] == 2800


def test_section_prompt_kwargs_expanded_defaults():
    """无预算 → 提示词槽位用展开默认（下限 2000 / 目标 3000-6000）。"""
    a = _shape_agent("Deep multi-decade geopolitical outlook, no page limit.")
    kw = a._section_prompt_kwargs()
    assert kw["section_floor_chars"] == 2000
    assert kw["section_target_lo"] == 3000 and kw["section_target_hi"] == 6000


# ─────────────────────────── RQ-1: H3 sub-heading whitelist ──────────────────
def test_clean_section_content_preserves_h3_flattens_others():
    """章节体内 ### 三级小标题保留；#/##/#### 降级为粗体。"""
    content = (
        "开篇总论。\n\n"
        "### 首发引爆阶段\n\n正文一。\n\n"
        "## 不该出现的二级标题\n\n正文二。\n\n"
        "#### 太深的四级标题\n\n正文三。"
    )
    out = ReportManager._clean_section_content(content, "某章节")
    assert "### 首发引爆阶段" in out                 # H3 保留
    assert "**不该出现的二级标题**" in out            # H2 降级为粗体
    assert "## 不该出现的二级标题" not in out
    assert "**太深的四级标题**" in out                # H4 降级为粗体
    assert "#### 太深的四级标题" not in out


def test_post_process_report_preserves_h3():
    """整稿后处理保留 # 主标题 / ## 章节标题 / ### 子小节；#### 降级粗体。"""
    outline = ReportOutline(title="报告主标题", summary="S", sections=[
        ReportSection(title="章节甲"),
    ])
    content = (
        "# 报告主标题\n\n"
        "## 章节甲\n\n"
        "### 子小节一\n\n正文。\n\n"
        "#### 过深标题\n\n更多正文。"
    )
    out = ReportManager._post_process_report(content, outline)
    assert "# 报告主标题" in out
    assert "## 章节甲" in out
    assert "### 子小节一" in out                      # H3 保留
    assert "**过深标题**" in out and "#### 过深标题" not in out


def test_looks_contaminated_length_floor_and_figure_exemption():
    """RQ-1：短于下限判无效，但含图表标记的短章节豁免长度门。"""
    short = "太短了。" * 5                              # 远小于 800
    assert len(short.strip()) < MIN_VALID_SECTION_CHARS
    assert _looks_contaminated(short) is True
    # 含 Mermaid/内嵌图标记的短章节是合法图表产出 → 豁免
    assert _looks_contaminated(short + "\n```mermaid\ngraph TD;A-->B\n```") is False
    assert _looks_contaminated("图注。\n![chart](chart.png)") is False
