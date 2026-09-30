"""INFRA-5: the ReportAgent tool-call boundary.

Offline (scripted LLM doubles, no network):
  * report_tool_args: tolerant block parsing, envelope normalization, validate_call,
    the rejection budget and the corrective observation text;
  * ReAct: malformed / invalid calls become uncharged observations until the
    per-section cap, flat arguments are lifted, tool_unknown / tool_rejected rows;
  * native loop: arguments_error / invalid params / unknown names answered with a
    role=tool ERROR per tool_call_id, never dispatched or charged, assistant turn
    rebuilt from raw_arguments, charge after dispatch, evidence-preserving forced final,
    LLM_TRANSPORT_STRICT contamination fallback to ReAct;
  * chat() dispatch, and report telemetry tool_calls under concurrent sections;
  * every flag off restores the legacy behaviour.
"""

import json
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services import report_tool_args as rta  # noqa: E402
from app.services.report_agent import (  # noqa: E402
    ReportAgent, ReportLogger, ReportManager, ReportOutline, ReportSection, _looks_contaminated,
)

BODY = "这是一段足够长的中文正文内容。" * 60  # >= MIN_VALID_SECTION_CHARS (800)
EN_BODY = "This is a long enough English section body sentence. " * 30


# ─────────────────────────────────── helpers ───────────────────────────────────
def _tools(*names):
    return {n: {"name": n, "description": "d", "parameters": {}} for n in names}


def _agent(**over):
    a = ReportAgent.__new__(ReportAgent)
    a.graph_id = "g1"
    a.simulation_id = "sim1"
    a.simulation_requirement = "会发生什么？"
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
    a.tools = _tools("insight_forge", "quick_search", "trace_cascade")
    a.MIN_TOOL_CALLS_PER_SECTION = 1
    a.MAX_TOOL_CALLS_PER_SECTION = 12
    for k, v in over.items():
        setattr(a, k, v)
    return a


class _ScriptLLM:
    """chat() replays scripted replies and records every message list it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages=None, temperature=0.3, max_tokens=4096, **kw):
        self.calls.append([dict(m) for m in messages])
        return self.replies.pop(0) if self.replies else "Final Answer: " + BODY


class _NativeLLM:
    """chat_with_tools replays scripted turns (then a no-tool turn); chat() is the forced final."""

    def __init__(self, turns, final=BODY, idle_content=None):
        self.turns = list(turns)
        self.final = final
        self.idle_content = BODY if idle_content is None else idle_content
        self.tool_messages = []
        self.chat_calls = []

    def supports_native_tools(self):
        return True

    def chat_with_tools(self, messages, schemas, temperature=0.5, max_tokens=4096, **kw):
        self.tool_messages.append([dict(m) for m in messages])
        if self.turns:
            return self.turns.pop(0)
        return {"content": self.idle_content, "tool_calls": []}

    def chat(self, messages=None, temperature=0.5, max_tokens=4096, **kw):
        self.chat_calls.append([dict(m) for m in messages])
        return self.final


def _section():
    section = ReportSection(title="正文1")
    return section, ReportOutline(title="T", summary="S", sections=[section])


def _run_react(a):
    section, outline = _section()
    return a._generate_section_react(section, outline, previous_sections=[])


def _run_native(a):
    section, outline = _section()
    return a._generate_section_native(section, outline, previous_sections=[])


def _user_texts(calls):
    return [m["content"] for msgs in calls for m in msgs
            if m.get("role") == "user" and isinstance(m.get("content"), str)]


def _read_agent_log(tmp_path, report_id):
    path = tmp_path / "reports" / report_id / "agent_log.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _recording_executor(a):
    executed = []

    def _exec(name, params, report_context=""):
        executed.append((name, dict(params) if isinstance(params, dict) else params))
        return f"RESULT[{name}]"

    a._execute_tool = _exec
    return executed


@pytest.fixture
def report_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    return tmp_path


# ─────────────────────────────────── knobs ───────────────────────────────────
def test_knob_defaults_and_env_example_documentation():
    assert Config.REPORT_TOOL_ARG_REPAIR is True
    assert Config.REPORT_TOOL_MAX_REJECTED_PER_SECTION == 6
    assert Config.REPORT_NATIVE_FINAL_WITH_EVIDENCE is True
    assert Config.REPORT_NATIVE_FINAL_EVIDENCE_CHARS == 12000
    env_example = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                               ".env.example")
    with open(env_example, encoding="utf-8") as fh:
        text = fh.read()
    for line in ("# REPORT_TOOL_ARG_REPAIR=true", "# REPORT_TOOL_MAX_REJECTED_PER_SECTION=6",
                 "# REPORT_NATIVE_FINAL_WITH_EVIDENCE=true", "# REPORT_NATIVE_FINAL_EVIDENCE_CHARS=12000"):
        assert line in text


# ───────────────────────────── parse_tool_call_block ─────────────────────────────
def test_parse_block_valid_json_needs_no_repair():
    obj, repair, error = rta.parse_tool_call_block('{"name":"x","parameters":{"q":"a"}}')
    assert obj == {"name": "x", "parameters": {"q": "a"}} and repair is None and error is None


def test_parse_block_trailing_content_takes_first_object():
    obj, repair, error = rta.parse_tool_call_block('{"name":"x","parameters":{}} trailing')
    assert obj == {"name": "x", "parameters": {}}
    assert repair == rta.REPAIR_FIRST_OBJECT and error is None
    obj, repair, _ = rta.parse_tool_call_block(
        '{"name":"a","parameters":{"query":"1"}}\n{"name":"b","parameters":{"query":"2"}}')
    assert obj["name"] == "a" and repair == rta.REPAIR_FIRST_OBJECT


def test_parse_block_missing_braces_are_balanced():
    obj, repair, error = rta.parse_tool_call_block('{"name":"x","parameters":{"q":"a"}')
    assert obj == {"name": "x", "parameters": {"q": "a"}}
    assert repair == rta.REPAIR_BRACE_BALANCED and error is None
    obj, repair, _ = rta.parse_tool_call_block('{"name":"x","parameters":{"q":"a{b}",')
    assert obj == {"name": "x", "parameters": {"q": "a{b}"}} and repair == rta.REPAIR_BRACE_BALANCED


def test_parse_block_leading_text_is_skipped():
    obj, repair, _ = rta.parse_tool_call_block('```json\n{"name":"x","parameters":{}}')
    assert obj == {"name": "x", "parameters": {}} and repair == rta.REPAIR_LEADING_TEXT


def test_parse_block_zero_width_characters_are_removed():
    obj, repair, _ = rta.parse_tool_call_block('{"name":"x","parameters":{}}\u200d')
    assert obj == {"name": "x", "parameters": {}} and repair == rta.REPAIR_INVISIBLE_CHARS
    # logged GLM shape: a zero-width joiner where the outer closing brace should be
    obj, repair, _ = rta.parse_tool_call_block('{"name":"x","parameters":{"q":"a"}\u200d')
    assert obj == {"name": "x", "parameters": {"q": "a"}} and repair == rta.REPAIR_BRACE_BALANCED


@pytest.mark.parametrize("text", [
    "garbage", "", "   ", '{"name":"x","parameters":{"q":"trunc', '{"name":"x"]', "[1, 2]",
])
def test_parse_block_unrecoverable_returns_error(text):
    obj, repair, error = rta.parse_tool_call_block(text)
    assert obj is None and repair is None
    assert isinstance(error, str) and error


# ───────────────────────────────── normalize_envelope ─────────────────────────────────
def test_normalize_aliases_tool_and_args():
    call, repairs = rta.normalize_envelope({"tool": "search", "args": {"q": "a"}})
    assert call == {"name": "search", "parameters": {"q": "a"}}
    assert repairs == [rta.REPAIR_ALIASED_KEYS]
    for alias in ("params", "arguments", "input"):
        call, _ = rta.normalize_envelope({"name": "search", alias: {"q": "a"}})
        assert call == {"name": "search", "parameters": {"q": "a"}}


def test_normalize_lifts_flat_arguments_but_not_envelope_keys():
    source = {"name": "search", "q": "a", "as_of": "2024", "id": "c1", "type": "function"}
    call, repairs = rta.normalize_envelope(source)
    assert call["parameters"] == {"q": "a", "as_of": "2024"}
    assert call["id"] == "c1" and call["type"] == "function"
    assert repairs == [rta.REPAIR_FLATTENED]
    assert "parameters" not in source  # input untouched
    call, repairs = rta.normalize_envelope({"name": "coalition_map"})
    assert call == {"name": "coalition_map", "parameters": {}} and repairs == []


def test_normalize_decodes_stringified_parameters_and_null():
    call, repairs = rta.normalize_envelope({"name": "search", "parameters": '{"q": "a"}'})
    assert call["parameters"] == {"q": "a"} and repairs == [rta.REPAIR_STRINGIFIED]
    call, repairs = rta.normalize_envelope({"name": "search", "parameters": None})
    assert call["parameters"] == {} and repairs == []
    call, _ = rta.normalize_envelope({"name": "search", "parameters": "gold price"})
    assert call["parameters"] == "gold price"  # left for validate_call to reject


# ─────────────────────────────────── validate_call ───────────────────────────────────
def test_validate_reports_missing_required_param():
    assert "query" in rta.validate_call("insight_forge", {})
    assert "query" in rta.validate_call("quick_search", {"query": "   "})
    assert "query" in rta.validate_call("search_graph", {})  # alias resolved to quick_search
    assert rta.validate_call("insight_forge", {"query": "q"}) is None
    # _execute_tool's fallbacks count: opinion_shift reads actor_name, else query
    assert rta.validate_call("opinion_shift", {"query": "Alice"}) is None
    assert "actor_name" in rta.validate_call("opinion_shift", {})
    assert rta.validate_call("coalition_map", {}) is None
    assert rta.validate_call("get_simulation_context", {}) is None  # supplies its own query


def test_validate_alternative_groups_for_trace_cascade():
    assert rta.validate_call("trace_cascade", {"source": "A", "target": "B"}) is None
    assert rta.validate_call("trace_cascade", {"center": "A"}) is None
    assert "source+target" in rta.validate_call("trace_cascade", {"source": "A"})


def test_validate_coerces_int_like_limit():
    params = {"query": "q", "limit": "5"}
    assert rta.validate_call("quick_search", params) is None
    assert params["limit"] == 5
    params = {"query": "q", "top_k": 3.0}
    assert rta.validate_call("quick_search", params) is None and params["top_k"] == 3
    params = {"query": "q", "limit": ""}
    assert rta.validate_call("quick_search", params) is None and "limit" not in params
    assert "limit" in rta.validate_call("quick_search", {"query": "q", "limit": "many"})
    assert "limit" in rta.validate_call("quick_search", {"query": "q", "limit": "0"})
    assert "limit" in rta.validate_call("quick_search", {"query": "q", "limit": True})
    assert "limit" in rta.validate_call("quick_search", {"query": "q", "limit": "2.5"})


def test_validate_as_of_must_parse():
    assert "as_of" in rta.validate_call("insight_forge", {"query": "q", "as_of": "someday"})
    assert rta.validate_call("insight_forge", {"query": "q", "as_of": "2024-06-30"}) is None
    assert rta.validate_call("insight_forge", {"query": "q", "as_of": 2025}) is None
    assert rta.validate_call("insight_forge", {"query": "q", "as_of": ""}) is None


def test_validate_rejects_non_object_parameters():
    assert "JSON 对象" in rta.validate_call("quick_search", "gold price")
    assert "JSON 对象" in rta.validate_call("quick_search", ["q"])


def test_rejection_budget_charges_after_cap_and_observation_text():
    budget = rta.RejectionBudget(6)
    assert [budget.register() for _ in range(7)] == [False] * 6 + [True]
    assert rta.RejectionBudget(-3).register() is True
    text = rta.rejection_observation(rta.KIND_ARGS_NOT_JSON, "Expecting value")
    assert text == ('工具调用参数不是有效的 JSON：Expecting value。请只输出一个 '
                    '<tool_call>{"name":...,"parameters":{...}}</tool_call>。')
    assert rta.CHARGED_NOTE in rta.rejection_observation(rta.KIND_ARGS_NOT_JSON, "x", charged=True)
    assert "quick_search" in rta.rejection_observation(rta.KIND_INVALID_PARAMS, "缺少必填参数 query",
                                                       tool_name="quick_search")


# ──────────────────────────────── _parse_tool_calls ────────────────────────────────
def test_parse_tool_calls_surfaces_malformed_blocks(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    a = _agent()
    calls = a._parse_tool_calls("<tool_call>{not json</tool_call>")
    assert len(calls) == 1 and calls[0]["_kind"] == rta.KIND_ARGS_NOT_JSON
    assert calls[0]["raw"] == "{not json" and calls[0]["_parse_error"]
    calls = a._parse_tool_calls('<tool_call>{"parameters": {"query": "q"}}</tool_call>')
    assert calls[0]["_kind"] == rta.KIND_MISSING_NAME
    calls = a._parse_tool_calls('<tool_call>\n{"name": "quick_search", "query": "q"}\n</tool_call>')
    assert calls == [{"name": "quick_search", "parameters": {"query": "q"},
                      "_repairs": [rta.REPAIR_FLATTENED]}]
    # bare JSON (no <tool_call> tag) gets the same repairs, only for live tool names
    calls = a._parse_tool_calls('我先检索。\n{"name": "insight_forge", "arguments": {"query": "q"}')
    assert calls[0]["parameters"] == {"query": "q"}
    assert a._parse_tool_calls('{"name": "not_a_tool", "query": "q"}') == []
    assert a._parse_tool_calls("正文里有花括号 {x} 但不是工具调用") == []


def test_parse_tool_calls_unterminated_block(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    a = _agent()
    # wrong closing tag: the call is recovered
    calls = a._parse_tool_calls(
        '先检索。\n<tool_call>\n{"name": "quick_search", "parameters": {"query": "q"}}\n</invoke>')
    assert calls == [{"name": "quick_search", "parameters": {"query": "q"},
                      "_repairs": [rta.REPAIR_UNTERMINATED_BLOCK, rta.REPAIR_FIRST_OBJECT]}]
    # reply cut off inside an argument string: surfaced, never truncated into a call
    calls = a._parse_tool_calls('<tool_call>\n{"name": "quick_search", "parameters": {"query": "Federal Res')
    assert len(calls) == 1 and calls[0]["_kind"] == rta.KIND_ARGS_NOT_JSON
    # an opener after the last closed block is parsed too; an opener inside one is not
    calls = a._parse_tool_calls(
        '<tool_call>{"name": "quick_search", "parameters": {"query": "a"}}</tool_call>'
        '<tool_call>{"name": "insight_forge", "parameters": {"query": "b"}')
    assert [c["name"] for c in calls] == ["quick_search", "insight_forge"]
    assert calls[1]["_repairs"] == [rta.REPAIR_UNTERMINATED_BLOCK, rta.REPAIR_BRACE_BALANCED]


def test_parse_tool_calls_flag_off_is_the_legacy_parser(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", False, raising=False)
    a = _agent()
    samples = [
        "<tool_call>{not json</tool_call>",
        '<tool_call>{"name":"quick_search","parameters":{"query":"q"}} trailing</tool_call>',
        '<tool_call>\n{"name": "quick_search", "query": "q"}\n</tool_call>',
        '<tool_call>\n{"tool": "quick_search", "params": {"query": "q"}}\n</tool_call>',
        '{"name": "insight_forge", "parameters": {"query": "q"}}',
        "plain prose",
    ]
    for text in samples:
        assert a._parse_tool_calls(text) == a._parse_tool_calls_legacy(text)
    # legacy semantics pinned: malformed blocks vanish, flat arguments are not lifted
    assert a._parse_tool_calls(samples[0]) == []
    assert a._parse_tool_calls(samples[2]) == [{"name": "quick_search", "query": "q"}]


# ─────────────────────────────────────── ReAct ───────────────────────────────────────
def test_react_malformed_call_is_surfaced_and_not_charged(monkeypatch, report_dir):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    a = _agent()
    a.report_logger = ReportLogger("r_react_malformed")
    a.llm = _ScriptLLM([
        '<tool_call>\n{"name": "quick_search", "parameters": {"query": "q"}\n{"extra"\n</tool_call>',
        '<tool_call>\n{"name": "quick_search", "parameters": {"query": "gold"}}\n</tool_call>',
        "Final Answer: " + BODY,
    ])
    executed = _recording_executor(a)
    result = _run_react(a)
    assert BODY in result
    assert executed == [("quick_search", {"query": "gold"})]
    assert a._section_tool_calls == 1  # the malformed block was not charged
    observations = _user_texts(a.llm.calls)
    assert any(t.startswith("工具调用参数不是有效的 JSON：") for t in observations)
    rows = _read_agent_log(report_dir, "r_react_malformed")
    rejected = [r for r in rows if r["action"] == "tool_rejected"]
    assert len(rejected) == 1
    assert rejected[0]["details"]["reason"].startswith("args_not_json")
    # skeleton only: no draft-prose fields the publication gate would have to withhold
    assert not {"content", "response", "thought"} & set(rejected[0]["details"])
    _, outcomes = a._tool_counters_snapshot()
    assert outcomes["rejected_parse"] == 1 and outcomes["dispatched"] == 1


def test_react_seventh_rejection_is_charged(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_TOOL_MAX_REJECTED_PER_SECTION", 6, raising=False)
    a = _agent()
    a.llm = _ScriptLLM(["<tool_call>{broken</tool_call>"] * 7 + ["Final Answer: " + BODY])
    executed = _recording_executor(a)
    result = _run_react(a)
    # the 7th rejection consumed budget, so MIN_TOOL_CALLS_PER_SECTION=1 is met and the
    # Final Answer is accepted on the 8th turn (an uncharged 7th would have been refused)
    assert BODY in result and len(a.llm.calls) == 8
    assert executed == []
    assert a._section_tool_calls == 1
    # the last turn's conversation holds every observation once, in order
    observations = [t for t in _user_texts(a.llm.calls[-1:]) if t.startswith("工具调用参数不是有效的 JSON")]
    assert len(observations) == 7
    assert all(rta.CHARGED_NOTE not in t for t in observations[:6])
    assert rta.CHARGED_NOTE in observations[6]
    _, outcomes = a._tool_counters_snapshot()
    assert outcomes["rejected_parse"] == 7


def test_react_invalid_params_rejected_before_dispatch(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    a = _agent()
    a.llm = _ScriptLLM([
        '<tool_call>{"name": "insight_forge", "parameters": {"query": ""}}</tool_call>',
        '<tool_call>{"name": "insight_forge", "query": "trend", "as_of": "2024"}</tool_call>',
        "Final Answer: " + BODY,
    ])
    executed = _recording_executor(a)
    assert BODY in _run_react(a)
    assert executed == [("insight_forge", {"query": "trend", "as_of": "2024"})]
    assert a._section_tool_calls == 1
    assert any("insight_forge 的参数无效" in t and "query" in t for t in _user_texts(a.llm.calls))
    _, outcomes = a._tool_counters_snapshot()
    assert outcomes["rejected_params"] == 1 and outcomes["repaired"] == 1


def test_react_flag_off_keeps_legacy_dispatch(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", False, raising=False)
    a = _agent()
    a.llm = _ScriptLLM([
        "<tool_call>{broken</tool_call>",
        '<tool_call>{"name": "insight_forge", "query": "trend"}</tool_call>',
        "Final Answer: " + BODY,
    ])
    executed = _recording_executor(a)
    assert BODY in _run_react(a)
    # legacy: the malformed block is dropped silently and flat arguments run with {}
    assert executed == [("insight_forge", {})]
    assert not any("不是有效的 JSON" in t for t in _user_texts(a.llm.calls))


def test_react_unknown_tool_logs_tool_unknown_row(monkeypatch, report_dir):
    a = _agent()
    a.report_logger = ReportLogger("r_react_unknown")
    a.llm = _ScriptLLM([
        '<tool_call>{"name": "interview_agents", "parameters": {"interview_topic": "t"}}</tool_call>',
        '<tool_call>{"name": "quick_search", "parameters": {"query": "q"}}</tool_call>',
        "Final Answer: " + BODY,
    ])
    _recording_executor(a)
    _run_react(a)
    unknown = [r for r in _read_agent_log(report_dir, "r_react_unknown") if r["action"] == "tool_unknown"]
    assert [r["details"] for r in unknown] == [{"tool_name": "interview_agents", "path": "react"}]
    assert a._section_tool_calls == 1


def test_execute_tool_fallback_logs_dispatch_path(report_dir):
    a = _agent()
    a.report_logger = ReportLogger("r_dispatch_unknown")
    assert "未知工具" in a._execute_tool("no_such_tool", {})
    unknown = [r for r in _read_agent_log(report_dir, "r_dispatch_unknown") if r["action"] == "tool_unknown"]
    assert [r["details"] for r in unknown] == [{"tool_name": "no_such_tool", "path": "dispatch"}]


# ─────────────────────────────────────── native ───────────────────────────────────────
def _tool_turn(*calls, content=""):
    return {"content": content, "tool_calls": list(calls)}


def _assistant_and_replies(messages):
    """Pairs each assistant tool_calls turn with the role=tool replies that follow it."""
    pairs = []
    for i, m in enumerate(messages):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            replies = []
            for follow in messages[i + 1:]:
                if follow.get("role") != "tool":
                    break
                replies.append(follow)
            pairs.append((m, replies))
    return pairs


def test_native_arguments_error_answered_not_dispatched_not_charged(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    a = _agent()
    bad = {"id": "c_bad", "name": "quick_search", "arguments": {},
           "raw_arguments": '{"query": "gold"', "arguments_error": "JSONDecodeError: Expecting ','"}
    good = {"id": "c_ok", "name": "quick_search", "arguments": {"query": "silver"},
            "raw_arguments": '{"query":"silver"}', "arguments_error": None}
    a.llm = _NativeLLM([_tool_turn(bad, good)])
    executed = _recording_executor(a)
    assert _run_native(a) == BODY
    assert executed == [("quick_search", {"query": "silver"})]
    assert a._section_tool_calls == 1
    final_messages = a.llm.tool_messages[-1]
    (assistant, replies), = _assistant_and_replies(final_messages)
    assert [tc["id"] for tc in assistant["tool_calls"]] == [r["tool_call_id"] for r in replies]
    by_id = {r["tool_call_id"]: r["content"] for r in replies}
    assert by_id["c_bad"].startswith("ERROR: ") and "JSON" in by_id["c_bad"]
    assert by_id["c_ok"] == "RESULT[quick_search]"
    # the assistant turn echoes what the model sent, not json.dumps({})
    sent = {tc["id"]: tc["function"]["arguments"] for tc in assistant["tool_calls"]}
    assert sent == {"c_bad": '{"query": "gold"', "c_ok": '{"query":"silver"}'}


def test_native_invalid_params_and_unknown_tool_rejected(monkeypatch, report_dir):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    a = _agent()
    a.report_logger = ReportLogger("r_native_reject")
    calls = [
        {"id": "u1", "name": "interview_agents", "arguments": {"interview_topic": "t"}},
        {"id": "p1", "name": "insight_forge", "arguments": {"query": " "}},
        {"id": "ok", "name": "insight_forge", "arguments": {"query": "q"}},
    ]
    a.llm = _NativeLLM([_tool_turn(*calls)])
    executed = _recording_executor(a)
    assert _run_native(a) == BODY
    assert executed == [("insight_forge", {"query": "q"})]
    assert a._section_tool_calls == 1
    (_assistant, replies), = _assistant_and_replies(a.llm.tool_messages[-1])
    by_id = {r["tool_call_id"]: r["content"] for r in replies}
    assert set(by_id) == {"u1", "p1", "ok"}
    assert by_id["u1"].startswith("ERROR: ") and "不是可用工具" in by_id["u1"]
    assert by_id["p1"].startswith("ERROR: ") and "query" in by_id["p1"]
    rows = _read_agent_log(report_dir, "r_native_reject")
    assert [r["details"] for r in rows if r["action"] == "tool_unknown"] == [
        {"tool_name": "interview_agents", "path": "native"}]
    assert [r["details"]["tool_name"] for r in rows if r["action"] == "tool_rejected"] == ["insight_forge"]
    _, outcomes = a._tool_counters_snapshot()
    assert outcomes == {"dispatched": 1, "rejected_parse": 0, "rejected_params": 1,
                        "rejected_unknown": 1, "repaired": 0}


def test_native_flag_off_keeps_legacy_dispatch_and_arguments(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", False, raising=False)
    a = _agent()
    bad = {"id": "c_bad", "name": "quick_search", "arguments": {},
           "raw_arguments": '{"query": "gold"', "arguments_error": "JSONDecodeError"}
    a.llm = _NativeLLM([_tool_turn(bad)])
    executed = _recording_executor(a)
    assert _run_native(a) == BODY
    assert executed == [("quick_search", {})]  # legacy: runs with the empty arguments
    assert a._section_tool_calls == 1
    (assistant, replies), = _assistant_and_replies(a.llm.tool_messages[-1])
    assert assistant["tool_calls"][0]["function"]["arguments"] == "{}"
    assert replies[0]["content"] == "RESULT[quick_search]"


def test_native_charges_only_after_dispatch(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    a = _agent()
    seen = []

    def _exec(name, params, report_context=""):
        seen.append(a._section_tool_calls)
        return "R"

    a._execute_tool = _exec
    a.llm = _NativeLLM([_tool_turn({"id": "c1", "name": "quick_search", "arguments": {"query": "q"}})])
    _run_native(a)
    assert seen == [0] and a._section_tool_calls == 1


def _exhausting_native(monkeypatch, evidence_flag, chars=12000):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_NATIVE_FINAL_WITH_EVIDENCE", evidence_flag, raising=False)
    monkeypatch.setattr(Config, "REPORT_NATIVE_FINAL_EVIDENCE_CHARS", chars, raising=False)
    a = _agent(MAX_TOOL_CALLS_PER_SECTION=2)
    call = {"id": "c1", "name": "quick_search", "arguments": {"query": "q"}}
    # one tool turn, then empty turns until the 14 iterations run out → forced final
    a.llm = _NativeLLM([_tool_turn(call)], idle_content="")
    a._execute_tool = lambda name, params, report_context="": "EVIDENCE-" + "x" * 500 + "-TAIL-MARK"
    assert _run_native(a) == BODY
    (final_messages,) = a.llm.chat_calls
    user_prompt = a.llm.tool_messages[0][1]["content"]
    return final_messages[-1]["content"], user_prompt


def test_native_forced_final_carries_evidence_digest(monkeypatch):
    final_user, user_prompt = _exhausting_native(monkeypatch, True)
    assert final_user.startswith(user_prompt + "\n\n【已检索到的工具结果（证据摘要）】\n【quick_search】\nEVIDENCE-")
    assert "-TAIL-MARK" in final_user
    assert final_user.endswith("请基于以上工具结果直接输出本章 Markdown 正文。")
    trimmed, _ = _exhausting_native(monkeypatch, True, chars=200)
    assert "…(中段略)…" in trimmed and "-TAIL-MARK" in trimmed


def test_native_forced_final_without_evidence_when_flag_off(monkeypatch):
    final_user, user_prompt = _exhausting_native(monkeypatch, False)
    assert final_user == user_prompt + "\n\n请直接输出本章 Markdown 正文。"  # the legacy prompt, byte for byte


# ───────────────────────────── reasoning-leak contamination ─────────────────────────────
def test_looks_contaminated_reasoning_markers_follow_transport_strict(monkeypatch):
    leaked = BODY + "\n<think>draft reasoning</think>"
    monkeypatch.setattr(Config, "LLM_TRANSPORT_STRICT", True, raising=False)
    assert _looks_contaminated(leaked) is True
    assert _looks_contaminated(BODY + "</think>") is True
    assert _looks_contaminated(BODY) is False
    monkeypatch.setattr(Config, "LLM_TRANSPORT_STRICT", False, raising=False)
    assert _looks_contaminated(leaked) is False


def _native_then_react_agent(native_final):
    a = _agent()

    class _BothLLM(_NativeLLM):
        def __init__(self):
            super().__init__([], final=None, idle_content=native_final)
            self.react_calls = 0

        def chat(self, messages=None, temperature=0.5, max_tokens=4096, **kw):
            self.react_calls += 1
            if self.react_calls == 1:
                return '<tool_call>{"name": "quick_search", "parameters": {"query": "q"}}</tool_call>'
            return "Final Answer: " + EN_BODY

    a.llm = _BothLLM()
    _recording_executor(a)
    a.MIN_TOOL_CALLS_PER_SECTION = 0
    return a


def test_native_think_leak_falls_back_to_react_when_strict(monkeypatch):
    monkeypatch.setattr(Config, "LLM_TRANSPORT_STRICT", True, raising=False)
    a = _native_then_react_agent("<think>plan</think>\n" + BODY)
    section, outline = _section()
    out = a._generate_section(section, outline, previous_sections=[])
    assert out == EN_BODY.strip()
    assert a.llm.react_calls >= 1  # native raised, ReAct produced the section


def test_native_think_leak_kept_when_not_strict(monkeypatch):
    monkeypatch.setattr(Config, "LLM_TRANSPORT_STRICT", False, raising=False)
    leaked = "<think>plan</think>\n" + BODY
    a = _native_then_react_agent(leaked)
    section, outline = _section()
    assert a._generate_section(section, outline, previous_sections=[]) == leaked
    assert a.llm.react_calls == 0


# ─────────────────────────────────────── chat() ───────────────────────────────────────
def test_chat_dispatch_surfaces_malformed_call(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    a = _agent()
    a._resolve_report_cached = lambda: None
    a.llm = _ScriptLLM([
        "<tool_call>{broken</tool_call>",
        '<tool_call>{"name": "quick_search", "query": "gold"}</tool_call>',
        "黄金价格上行。",
    ])
    executed = _recording_executor(a)
    out = a.chat("金价怎么样？")
    assert executed == [("quick_search", {"query": "gold"})]
    assert out["tool_calls"] == [{"name": "quick_search", "parameters": {"query": "gold"}}]
    assert out["sources"] == ["gold"]
    assert any(t.startswith("工具调用参数不是有效的 JSON") for t in _user_texts(a.llm.calls))


def test_chat_dispatch_flag_off_is_legacy(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", False, raising=False)
    a = _agent()
    a._resolve_report_cached = lambda: None
    a.llm = _ScriptLLM(["<tool_call>{broken</tool_call>前文"])
    executed = _recording_executor(a)
    out = a.chat("金价怎么样？")
    assert executed == [] and out == {"response": "前文", "tool_calls": [], "sources": []}


# ───────────────────────────── telemetry under concurrency ─────────────────────────────
class _ThreadSafeReactLLM:
    """Stateless per conversation: the first section turn calls a tool, later turns answer."""

    def __init__(self):
        self.lock = threading.Lock()
        self.turns = 0

    def chat(self, messages=None, temperature=0.5, max_tokens=4096, **kw):
        with self.lock:
            self.turns += 1
        if len(messages) == 2 and messages[0].get("role") == "system":
            return '<tool_call>{"name": "quick_search", "parameters": {"query": "q"}}</tool_call>'
        return "Final Answer: " + EN_BODY


def test_concurrent_sections_report_tool_calls_and_dispatch_counters(monkeypatch, report_dir):
    monkeypatch.setattr(Config, "REPORT_SECTION_CONCURRENCY", 3, raising=False)
    monkeypatch.setattr(Config, "REPORT_SECTION_RETRY_MAX", 0, raising=False)
    monkeypatch.setattr(Config, "REPORT_STRUCTURED_FORECAST", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_SIGNAL_PACK", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_SECTION_REFLECTION", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_SECTION_LANG_ENFORCE", False, raising=False)
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_TELEMETRY", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    a = _agent()
    outline = ReportOutline(title="T", summary="S", sections=[
        ReportSection(title=f"Body {i}") for i in range(1, 5)
    ])
    a.plan_outline = lambda progress_callback=None, forecast_spine_block="", \
        require_forecast_structure=False: outline
    a.llm = _ThreadSafeReactLLM()
    executed = _recording_executor(a)
    a._generate_section = (
        lambda section, outline, previous_sections, progress_callback=None, section_index=0:
        a._generate_section_react(section, outline, previous_sections, progress_callback, section_index))
    report = a.generate_report(report_id="r_concurrent_tools")
    assert len(executed) == 4
    totals = report.telemetry["totals"]
    assert report.telemetry["sections"] == []  # per-section rollup is skipped when concurrent
    assert totals["tool_calls"] == 4  # was 0 before INFRA-5
    assert totals["tool_dispatch"]["dispatched"] == 4
    assert set(totals["tool_dispatch"]) == set(rta.TOOL_OUTCOME_KEYS)
    on_disk = json.loads((report_dir / "reports" / "r_concurrent_tools" / "telemetry.json")
                         .read_text(encoding="utf-8"))
    assert on_disk["totals"]["tool_calls"] == 4
