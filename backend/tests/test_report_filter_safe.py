"""Content-filter-safe section generation (report stage).

Live defect (pipe_d569f211eb14, glm-5.3): one chapter was content-filtered on all six
attempts and the publish gate refused the whole report.  The agent log showed a complete,
filter-clean draft rejected only for the tool-call floor, after which the accumulated
retrieval dumps tripped the provider's input filter; the identical retries (and the LLM
cache) replayed the failure.  Live probes showed the brief and an institutional-register
directive pass while rewriting leaders' names as offices is itself a trigger.

Pins: a draft rejected only for the tool-call floor is accepted when a content filter
interrupts the attempt (both generators, loop and forced-finish calls), recorded as level 0,
never for other errors or without a draft; the retry wrapper climbs the ladder only on a
content filter, without backoff, records the level, keeps the legacy backoff path for other
errors and can be switched off; the native path no longer falls back to ReAct on a content
filter; level 1 adds the directive, lowers the floor to one and caps passages; level 2
writes tool-free; the tool-call parser accepts flat and OpenAI-style arguments; the report
discloses the chapters written this way.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services import report_agent as ra  # noqa: E402
from app.services import report_filter_safe as fs  # noqa: E402
from app.services.report_agent import (  # noqa: E402
    Report, ReportAgent, ReportOutline, ReportSection, ReportStatus, SECTION_FAILURE_PLACEHOLDER,
)


class _ContentFilterError(Exception):
    pass


_FILTER_TEXT = ("Error code: 400 - {'contentFilter': [{'level': 1, 'role': 'user'}], 'error': "
                "{'code': '1301', 'message': '系统检测到输入或生成内容可能包含不安全或敏感内容'}}")
_BODY = "The commerce ministry keeps the suspension in force while tightening licensing. " * 20
_TOOL_CALL = '<tool_call>{"name": "quick_search", "parameters": {"query": "who decides"}}</tool_call>'


def _bare_agent(**over):
    a = ReportAgent.__new__(ReportAgent)
    a.graph_id = "g1"
    a.simulation_id = "sim1"
    a.simulation_requirement = "What happens to the truce?"
    a.situation_brief = ""
    a.actors = None
    a.sources = []
    a.research_report = ""
    a.output_language = "English"
    a.scenario_label = ""
    a.base_simulation_id = None
    a._background_block = ""
    a._sources_index = ""
    a._signal_pack = ""
    a._forecast_spine = None
    a._forecast_spine_block = ""
    a._retrieval_query = None
    a._outline_degraded = False
    a._outline_summary = ""
    a._section_tool_calls = 0
    a.report_logger = None
    a.console_logger = None
    a.tools = {"quick_search": {"name": "quick_search", "description": "d", "parameters": {}},
               "insight_forge": {"name": "insight_forge", "description": "d", "parameters": {}}}
    a.MIN_TOOL_CALLS_PER_SECTION = 2
    a.MAX_TOOL_CALLS_PER_SECTION = 4
    for k, v in over.items():
        setattr(a, k, v)
    return a


def _section():
    return ReportSection(
        title="The Actor Architecture: Who Actually Decides the Outcome",
        description="Trump's personal control of tariff levels; Xi's preference for extending truces [S25].")


def _outline(section):
    return ReportOutline(title="T", summary="S", sections=[section])


# ----------------------------------------------------------------------------- module
def test_directive_levels_caps_and_detector():
    assert fs.register_directive(0) == ""
    assert "Institutional-register mode" in fs.register_directive(1)
    assert "must not issue tool calls" not in fs.register_directive(1)
    assert "must not issue tool calls" in fs.register_directive(2)
    assert "Xi" not in fs.register_directive(2) and "top leader" not in fs.register_directive(2)
    assert fs.cap_observation("x" * 7000, 0) == "x" * 7000
    capped = fs.cap_observation("x" * 7000, 1)
    assert capped.startswith("x" * 6000) and "passage capped" in capped and len(capped) < 6200
    assert fs.cap_observation(None, 1) == ""
    assert fs.is_content_filter(_ContentFilterError(_FILTER_TEXT)) is True
    assert fs.is_content_filter(RuntimeError("transient 500")) is False
    assert fs.level_label(0).startswith("L0") and fs.level_label(2).startswith("L2")


# ----------------------------------------------------------------------------- retry ladder
def _ladder_agent(monkeypatch, script, retries=2):
    monkeypatch.setattr(Config, "REPORT_SECTION_RETRY_MAX", retries, raising=False)
    monkeypatch.setattr(Config, "REPORT_SECTION_RETRY_BACKOFF_S", 8.0, raising=False)
    sleeps = []
    monkeypatch.setattr(ra.time, "sleep", lambda s: sleeps.append(s))
    a = _bare_agent()
    seen = []

    def _gen(section, outline, previous_sections, progress_callback=None, section_index=0, **kw):
        seen.append(dict(kw))
        action = script[min(len(seen) - 1, len(script) - 1)]
        if isinstance(action, Exception):
            raise action
        return action

    a._generate_section = _gen
    return a, seen, sleeps


def test_content_filter_climbs_ladder_without_backoff_and_is_recorded(monkeypatch):
    a, seen, sleeps = _ladder_agent(
        monkeypatch, [_ContentFilterError(_FILTER_TEXT), _ContentFilterError(_FILTER_TEXT), "ok-body"])
    section = _section()
    assert a._generate_section_with_retry(section, _outline(section), []) == "ok-body"
    assert seen == [{}, {"filter_safe": 1}, {"filter_safe": 2}]
    assert sleeps == []                                                       # no pointless backoff
    assert a._filter_safe_sections == {section.title: 2}


def test_level_one_success_is_recorded_as_level_one(monkeypatch):
    a, seen, sleeps = _ladder_agent(monkeypatch, [_ContentFilterError(_FILTER_TEXT), "ok-body"])
    section = _section()
    assert a._generate_section_with_retry(section, _outline(section), []) == "ok-body"
    assert seen == [{}, {"filter_safe": 1}] and sleeps == []
    assert a._filter_safe_sections == {section.title: 1}


def test_transient_errors_keep_the_legacy_backoff_path(monkeypatch):
    a, seen, sleeps = _ladder_agent(monkeypatch, [RuntimeError("transient 500"), "ok-body"])
    section = _section()
    assert a._generate_section_with_retry(section, _outline(section), []) == "ok-body"
    assert seen == [{}, {}]                                                   # never a filter_safe kwarg
    assert sleeps == [8.0]
    assert not getattr(a, "_filter_safe_sections", None)


def test_filter_at_top_level_falls_back_to_backoff_then_raises(monkeypatch):
    a, seen, sleeps = _ladder_agent(monkeypatch, [_ContentFilterError(_FILTER_TEXT)], retries=3)
    section = _section()
    with pytest.raises(_ContentFilterError):
        a._generate_section_with_retry(section, _outline(section), [])
    assert seen == [{}, {"filter_safe": 1}, {"filter_safe": 2}, {"filter_safe": 2}]
    assert sleeps == [24.0]                                                   # one legacy backoff at the top rung
    assert not getattr(a, "_filter_safe_sections", None)


def test_ladder_off_switch_restores_legacy_identical_retries(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_FILTER_SAFE_LADDER", False, raising=False)
    a, seen, sleeps = _ladder_agent(monkeypatch, [_ContentFilterError(_FILTER_TEXT), "ok-body"])
    section = _section()
    assert a._generate_section_with_retry(section, _outline(section), []) == "ok-body"
    assert seen == [{}, {}] and sleeps == [8.0]


def test_no_retries_configured_is_unchanged(monkeypatch):
    a, seen, sleeps = _ladder_agent(monkeypatch, [_ContentFilterError(_FILTER_TEXT)], retries=0)
    section = _section()
    with pytest.raises(_ContentFilterError):
        a._generate_section_with_retry(section, _outline(section), [])
    assert seen == [{}] and sleeps == []


def test_dispatcher_skips_react_fallback_on_content_filter_only():
    class _LLM:
        def supports_native_tools(self):
            return True

    a = _bare_agent(llm=_LLM())
    react_calls = []
    a._generate_section_react = lambda *args, **kw: react_calls.append(kw) or "react-body"
    a._generate_section_native = lambda *args, **kw: (_ for _ in ()).throw(_ContentFilterError(_FILTER_TEXT))
    section = _section()
    with pytest.raises(_ContentFilterError):
        a._generate_section(section, _outline(section), [], None, 1, filter_safe=1)
    assert react_calls == []
    a._generate_section_native = lambda *args, **kw: (_ for _ in ()).throw(RuntimeError("native 500"))
    assert a._generate_section(section, _outline(section), [], None, 1, filter_safe=1) == "react-body"
    assert react_calls == [{"filter_safe": 1}]


# ----------------------------------------------------------------------------- ReAct path
class _ReactLLM:
    """Scripted chat(): a str is returned, an Exception is raised, None is returned as None."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, temperature=0.5, max_tokens=4096, **kw):
        self.calls.append([dict(m) for m in messages])
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def supports_native_tools(self):
        return False


def test_react_accepts_the_floor_rejected_draft_when_retrieval_is_content_filtered():
    # the live sequence: one tool call, a complete Final Answer rejected for 1 < 2 tool calls,
    # the model keeps retrieving, the next request is content-filtered on the input side
    llm = _ReactLLM([_TOOL_CALL, "Final Answer: " + _BODY, _TOOL_CALL, _ContentFilterError(_FILTER_TEXT)])
    a = _bare_agent(llm=llm)
    a._execute_tool = lambda name, params, report_context="": "retrieved passage [S3]"
    section = _section()
    out = a._generate_section_react(section, _outline(section), [], None, 6)
    assert out == _BODY.strip()
    assert len(llm.calls) == 4
    assert a._filter_safe_sections == {section.title: 0}


def test_react_without_a_draft_or_with_other_errors_still_raises():
    llm = _ReactLLM([_TOOL_CALL, _ContentFilterError(_FILTER_TEXT)])
    a = _bare_agent(llm=llm)
    a._execute_tool = lambda *args, **kw: "passage"
    section = _section()
    with pytest.raises(_ContentFilterError):
        a._generate_section_react(section, _outline(section), [], None, 6)
    llm2 = _ReactLLM([_TOOL_CALL, "Final Answer: " + _BODY, RuntimeError("provider 500")])
    a2 = _bare_agent(llm=llm2)
    a2._execute_tool = lambda *args, **kw: "passage"
    with pytest.raises(RuntimeError):
        a2._generate_section_react(section, _outline(section), [], None, 6)
    assert not getattr(a2, "_filter_safe_sections", None)
    # a contaminated / too-short Final Answer is never kept as the draft
    llm3 = _ReactLLM([_TOOL_CALL, "Final Answer: too short", _ContentFilterError(_FILTER_TEXT)])
    a3 = _bare_agent(llm=llm3)
    a3._execute_tool = lambda *args, **kw: "passage"
    with pytest.raises(_ContentFilterError):
        a3._generate_section_react(section, _outline(section), [], None, 6)


def test_react_draft_acceptance_respects_the_off_switch(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_FILTER_SAFE_LADDER", False, raising=False)
    llm = _ReactLLM([_TOOL_CALL, "Final Answer: " + _BODY, _TOOL_CALL, _ContentFilterError(_FILTER_TEXT)])
    a = _bare_agent(llm=llm)
    a._execute_tool = lambda *args, **kw: "passage"
    section = _section()
    with pytest.raises(_ContentFilterError):
        a._generate_section_react(section, _outline(section), [], None, 6)


def test_react_level_one_adds_directive_lowers_floor_and_caps_observations():
    llm = _ReactLLM([_TOOL_CALL, "Final Answer: " + _BODY])
    a = _bare_agent(llm=llm, _background_block="【背景档案】Xi Jinping and He Lifeng negotiate; Trump sets tariffs.")
    a._execute_tool = lambda name, params, report_context="": "passage [S3] " + "y" * 9000
    section = _section()
    out = a._generate_section_react(section, _outline(section), ["## Baseline\n\nprior chapter"], None, 6,
                                    filter_safe=1)
    assert out == _BODY.strip()                                              # 1 tool call now satisfies the floor
    system = llm.calls[0][0]["content"]
    assert "Xi Jinping and He Lifeng negotiate" in system                     # names are not rewritten
    assert "Institutional-register mode" in system and "must not issue tool calls" not in system
    observation = llm.calls[1][-1]["content"]
    assert "passage [S3]" in observation and "passage capped" in observation
    assert observation.count("y") < 6100


def test_react_level_zero_is_untouched():
    llm = _ReactLLM([_TOOL_CALL, "Final Answer: " + _BODY, _TOOL_CALL, "Final Answer: " + _BODY])
    a = _bare_agent(llm=llm, _background_block="Background block.")
    a._execute_tool = lambda name, params, report_context="": "passage " + "y" * 9000
    section = _section()
    out = a._generate_section_react(section, _outline(section), ["prior"], None, 6)
    assert out == _BODY.strip()
    assert len(llm.calls) == 4                                                # floor of 2 enforced as before
    assert "Institutional-register mode" not in llm.calls[0][0]["content"]
    assert llm.calls[1][-1]["content"].count("y") == 9000                     # no cap at level 0


def test_react_level_two_writes_without_tools_and_handles_contamination():
    llm = _ReactLLM(["Final Answer: " + _BODY])
    a = _bare_agent(llm=llm)
    a._execute_tool = lambda *args, **kw: pytest.fail("tools must not run at level 2")
    section = _section()
    prior = "## Baseline\n\n" + ("Xi Jinping met Trump. " * 400)
    out = a._generate_section_react(section, _outline(section), [prior], None, 6, filter_safe=2)
    assert out == _BODY.strip()
    assert len(llm.calls) == 1
    system, user = llm.calls[0][0]["content"], llm.calls[0][1]["content"]
    assert "must not issue tool calls" in system
    assert user.rstrip().endswith("开头输出本章完整 Markdown 正文。")
    assert 100 < user.count("met Trump") <= 190 and "..." in user           # prior chapter capped at 4000 chars
    llm2 = _ReactLLM(["Final Answer: too short"])
    a2 = _bare_agent(llm=llm2)
    assert a2._generate_section_react(section, _outline(section), [], None, 6, filter_safe=2) == SECTION_FAILURE_PLACEHOLDER
    llm3 = _ReactLLM([None])
    a3 = _bare_agent(llm=llm3)
    with pytest.raises(RuntimeError):
        a3._generate_section_react(section, _outline(section), [], None, 6, filter_safe=2)


# ----------------------------------------------------------------------------- native path
class _NativeLLM:
    """Scripted chat_with_tools(): dict responses in order; an Exception is raised."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.tool_calls = []
        self.chat_calls = []

    def chat_with_tools(self, messages, schemas, temperature=0.5, max_tokens=4096):
        self.tool_calls.append(([dict(m) for m in messages], list(schemas)))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def chat(self, messages, temperature=0.5, max_tokens=4096, **kw):
        self.chat_calls.append([dict(m) for m in messages])
        return _BODY

    def supports_native_tools(self):
        return True


_NATIVE_CALL = {"content": "", "tool_calls": [{"id": "c1", "name": "quick_search", "arguments": {"query": "q"}}]}


def test_native_accepts_floor_rejected_draft_and_caps_passages_at_level_one():
    llm = _NativeLLM([_NATIVE_CALL, {"content": _BODY, "tool_calls": []}, _NATIVE_CALL,
                      _ContentFilterError(_FILTER_TEXT)])
    a = _bare_agent(llm=llm)
    a._execute_tool = lambda name, args, report_context="": "passage [S3]"
    section = _section()
    assert a._generate_section_native(section, _outline(section), [], None, 6) == _BODY.strip()
    assert a._filter_safe_sections == {section.title: 0}

    llm2 = _NativeLLM([_NATIVE_CALL, {"content": _BODY, "tool_calls": []}])
    a2 = _bare_agent(llm=llm2, _background_block="Xi Jinping negotiates.")
    a2._execute_tool = lambda name, args, report_context="": "passage " + "y" * 9000
    out = a2._generate_section_native(section, _outline(section), ["prior"], None, 6, filter_safe=1)
    assert out == _BODY                                                       # floor lowered to 1
    system = llm2.tool_calls[0][0][0]["content"]
    assert "Xi Jinping negotiates." in system and "Institutional-register mode" in system
    tool_msg = [m for m in llm2.tool_calls[1][0] if m.get("role") == "tool"][0]
    assert tool_msg["content"].count("y") < 6100 and "passage capped" in tool_msg["content"]

    llm3 = _NativeLLM([])
    a3 = _bare_agent(llm=llm3)
    a3._execute_tool = lambda *args, **kw: pytest.fail("tools must not run at level 2")
    assert a3._generate_section_native(section, _outline(section), [], None, 6, filter_safe=2) == _BODY.strip()
    assert llm3.tool_calls == [] and len(llm3.chat_calls) == 1
    assert "must not issue tool calls" in llm3.chat_calls[0][0]["content"]


# ----------------------------------------------------------------------------- parser
def test_parse_tool_calls_accepts_flat_and_openai_style_arguments():
    a = _bare_agent()
    flat = a._parse_tool_calls('<tool_call>\n{"name": "quick_search", "query": "Trump Xi roles", "limit": 10}\n</tool_call>')
    assert flat[0]["name"] == "quick_search"
    assert flat[0]["parameters"] == {"query": "Trump Xi roles", "limit": 10}
    openai_style = a._parse_tool_calls('<tool_call>{"name": "quick_search", "arguments": {"query": "q"}}</tool_call>')
    assert openai_style[0]["parameters"] == {"query": "q"}
    bare = a._parse_tool_calls('<tool_call>{"name": "coalition_map"}</tool_call>')
    assert bare[0]["name"] == "coalition_map" and bare[0].get("parameters", {}) == {}
    legacy = a._parse_tool_calls('<tool_call>{"tool": "quick_search", "params": {"query": "q"}}</tool_call>')
    assert legacy[0]["name"] == "quick_search" and legacy[0]["parameters"] == {"query": "q"}


# ----------------------------------------------------------------------------- disclosure
def test_report_to_dict_discloses_filter_safe_sections_only_when_present():
    r = Report(report_id="r", simulation_id="s", graph_id="g", simulation_requirement="q",
               status=ReportStatus.COMPLETED)
    assert "filter_safe_sections" not in r.to_dict()
    r.filter_safe_sections = {"The Actor Architecture": 0}
    assert r.to_dict()["filter_safe_sections"] == {"The Actor Architecture": 0}
    assert r.to_dict()["partial"] is False


def test_record_filter_safe_section_keeps_the_highest_level_and_tolerates_bare_agents():
    a = _bare_agent()
    a._record_filter_safe_section("A", 0)
    assert a._filter_safe_sections == {"A": 0}
    a._record_filter_safe_section("A", 2)
    a._record_filter_safe_section("A", 1)
    a._record_filter_safe_section("B", 1)
    assert a._filter_safe_sections == {"A": 2, "B": 1}
