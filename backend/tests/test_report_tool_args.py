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
  * every flag off restores the legacy behaviour;
  * review round 1: linear block splitting (no regex backtracking on model text),
    zero-width characters kept inside values, malformed blocks beside a valid one
    recorded, skeleton-only rejection excerpts, blank-primary fallbacks, the tool
    contracts pinned to _define_tools / _execute_tool, and the native name check
    failing closed;
  * review round 2: fail-closed excerpts (no draft prose even without a JSON object),
    charged rejections never meeting the per-section tool minimum, capped rows for
    the malformed blocks of a degenerate reply, a call after leading prose braces,
    and a bare call missing its outer brace.
"""

import inspect
import json
import os
import re
import sys
import threading
import time

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
        self.max_tokens = []

    def chat(self, messages=None, temperature=0.3, max_tokens=4096, **kw):
        self.calls.append([dict(m) for m in messages])
        self.max_tokens.append(max_tokens)
        return self.replies.pop(0) if self.replies else "Final Answer: " + BODY


class _NativeLLM:
    """chat_with_tools replays scripted turns (then a no-tool turn); chat() is the forced final."""

    def __init__(self, turns, final=BODY, idle_content=None):
        self.turns = list(turns)
        self.final = final
        self.idle_content = BODY if idle_content is None else idle_content
        self.tool_messages = []
        self.tool_max_tokens = []
        self.chat_calls = []

    def supports_native_tools(self):
        return True

    def chat_with_tools(self, messages, schemas, temperature=0.5, max_tokens=4096, **kw):
        self.tool_messages.append([dict(m) for m in messages])
        self.tool_max_tokens.append(max_tokens)
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


def test_parse_block_call_after_leading_prose_braces():
    call = {"name": "quick_search", "parameters": {"query": "q"}}
    # review round 2: a '{' in the leading prose used to hide the real call (args_not_json)
    obj, repair, _ = rta.parse_tool_call_block('我用 {query} 检索\n{"name":"quick_search","parameters":{"query":"q"}}')
    assert obj == call and repair == rta.REPAIR_LEADING_TEXT
    obj, repair, _ = rta.parse_tool_call_block(
        '说明 {a} [b] {c}\n{"tool":"quick_search","args":{"query":"q"}} 然后')
    assert obj == {"tool": "quick_search", "args": {"query": "q"}} and repair == rta.REPAIR_FIRST_OBJECT
    # ... and when that call also lost its outer brace
    obj, repair, _ = rta.parse_tool_call_block('我用 {query} 检索\n{"name":"quick_search","parameters":{"query":"q"}')
    assert obj == call and repair == rta.REPAIR_BRACE_BALANCED
    # a call-shaped object nested inside the call is never taken for the call
    obj, repair, _ = rta.parse_tool_call_block(
        '{"name":"insight_forge","parameters":{"query":"x","ctx":{"name":"quick_search","parameters":{}}}')
    assert obj["name"] == "insight_forge" and repair == rta.REPAIR_BRACE_BALANCED
    # the openers tried are capped: a call behind more than _MAX_OPENER_ATTEMPTS undecodable
    # ones is surfaced as an error, not searched for without bound
    noisy = "{x} " + '{"name": oops} ' * (rta._MAX_OPENER_ATTEMPTS + 2) + '{"name":"quick_search","parameters":{}}'
    obj, _, error = rta.parse_tool_call_block(noisy)
    assert obj is None and error
    # an unclosed prose brace hides it (it looks like the call's own nesting): surfaced, not guessed
    obj, _, error = rta.parse_tool_call_block('我用 {query 检索\n{"name":"quick_search","parameters":{"query":"q"}}')
    assert obj is None and error


def test_parse_block_zero_width_characters_are_removed():
    obj, repair, _ = rta.parse_tool_call_block('{"name":"x","parameters":{}}\u200d')
    assert obj == {"name": "x", "parameters": {}} and repair == rta.REPAIR_INVISIBLE_CHARS
    # logged GLM shape: a zero-width joiner where the outer closing brace should be
    obj, repair, _ = rta.parse_tool_call_block('{"name":"x","parameters":{"q":"a"}\u200d')
    assert obj == {"name": "x", "parameters": {"q": "a"}} and repair == rta.REPAIR_BRACE_BALANCED


def test_parse_block_keeps_zero_width_characters_inside_values():
    # a ZWJ inside a value while the block fails for an unrelated reason (trailing text)
    obj, repairs, _ = rta.parse_tool_call_block_repairs(
        '{"name":"quick_search","parameters":{"query":"a\u200db"}}} x')
    assert obj["parameters"]["query"] == "a\u200db" and repairs == [rta.REPAIR_FIRST_OBJECT]
    # a BOM outside the JSON goes and is reported; the Persian ZWNJ inside the value stays
    obj, repairs, _ = rta.parse_tool_call_block_repairs(
        '\ufeff{"name":"x","parameters":{"q":"\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645"}} trailing')
    assert obj["parameters"]["q"] == "\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645"
    assert repairs == [rta.REPAIR_INVISIBLE_CHARS, rta.REPAIR_FIRST_OBJECT]
    # the spec contract reports the deciding repair
    obj, repair, _ = rta.parse_tool_call_block('\ufeff{"name":"x","parameters":{"q":"a"}} trailing')
    assert obj == {"name": "x", "parameters": {"q": "a"}} and repair == rta.REPAIR_FIRST_OBJECT


@pytest.mark.parametrize("text", [
    "garbage", "", "   ", '{"name":"x","parameters":{"q":"trunc', '{"name":"x"]', "[1, 2]",
])
def test_parse_block_unrecoverable_returns_error(text):
    obj, repair, error = rta.parse_tool_call_block(text)
    assert obj is None and repair is None
    assert isinstance(error, str) and error


# ─────────────────────────── block splitting / bare candidates ───────────────────────────
# The backtracking patterns these helpers replace; used here on small inputs only.
_LEGACY_BLOCK_RE = re.compile(r'<tool_call>\s*(.*?)\s*</tool_call>', re.DOTALL)
_LEGACY_BARE_RE = re.compile(r'(\{"(?:name|tool)"\s*:.*?\})\s*$', re.DOTALL)


@pytest.mark.parametrize("text", [
    "", "no tags", "<tool_call>{}</tool_call>", "<tool_call>  </tool_call>",
    '<tool_call>\n  {"a": 1}  \n</tool_call> tail <tool_call> x </tool_call>',
    "<tool_call><tool_call>{}</tool_call>", "</tool_call><tool_call>{}</tool_call>",
    "<tool_call>{} unclosed", "<tool_call>a</tool_call><tool_call>b",
])
def test_split_blocks_matches_the_lazy_regex_it_replaces(text):
    closed = [block for block, repair in rta.split_tool_call_blocks(text) if repair is None]
    assert closed == [m.group(1) for m in _LEGACY_BLOCK_RE.finditer(text)]


def test_split_blocks_unterminated_tail_is_the_text_after_the_last_opener():
    assert rta.split_tool_call_blocks("<tool_call>a</tool_call>x<tool_call> b <tool_call> c ") == [
        ("a", None), ("c", rta.REPAIR_UNTERMINATED_BLOCK)]
    assert rta.split_tool_call_blocks("<tool_call>a</tool_call> tail") == [("a", None)]


@pytest.mark.parametrize("text", [
    '{"name": "a", "parameters": {}}', 'pre {"name": "a"} mid {"tool": "b"}', '  {"x": 1}  ',
    'text {"name" : 1}', 'text {"name": 1} tail', '{"name":', "",
])
def test_bare_candidates_match_the_legacy_regex(text):
    stripped = text.strip()
    expected = [stripped] if stripped.startswith("{") and stripped.endswith("}") else []
    match = _LEGACY_BARE_RE.search(stripped)
    expected += [match.group(1)] if match else []
    assert rta.bare_tool_call_candidates(text) == expected


@pytest.mark.parametrize("reply, kind", [
    ("<tool_call>" + "\n" * 20000 + "{", rta.KIND_MISSING_NAME),  # "{" balances to {}: no name
    ("<tool_call>" * 5000, rta.KIND_ARGS_NOT_JSON),
    ("<tool_call>" + " " * 20000 + "x", rta.KIND_ARGS_NOT_JSON),
    ("<tool_call>{}</tool_call>" * 2000 + "<tool_call>" + "\n" * 20000, rta.KIND_ARGS_NOT_JSON),
    ("前文 " + '{"name": "quick_search", ' * 4000 + "}", None),
    ('{"name": "quick_search", ' * 4000, rta.KIND_ARGS_NOT_JSON),
    ("<tool_call>{x} " + '{"name": oops} ' * 4000 + "</tool_call>", rta.KIND_ARGS_NOT_JSON),
])
def test_parse_tool_calls_is_linear_on_degenerate_replies(monkeypatch, reply, kind):
    # the lazy block regex took ~12 s on an unclosed opener + 4,000 spaces, holding the GIL
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    a = _agent()
    started = time.perf_counter()
    calls = a._parse_tool_calls(reply)
    assert time.perf_counter() - started < 1.0
    if kind is None:
        assert calls == []
    else:
        assert calls and all("_parse_error" in c for c in calls)
        assert calls[-1]["_kind"] == kind


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


def test_validate_blank_primary_takes_the_fallback_value_in_place():
    # _execute_tool reads query only when interview_topic is absent, so a blank topic is filled
    params = {"interview_topic": "", "query": "宿舍甲醛"}
    assert rta.validate_call("interview_agents", params) is None
    assert params["interview_topic"] == "宿舍甲醛"
    params = {"actor_name": None, "query": "Alice"}
    assert rta.validate_call("opinion_shift", params) is None and params["actor_name"] == "Alice"
    params = {"query": "Alice"}
    assert rta.validate_call("opinion_shift", params) is None and params == {"query": "Alice"}
    assert "interview_topic" in rta.validate_call("interview_agents", {"interview_topic": " ", "query": ""})


def test_tool_contracts_match_report_agent_tool_definitions(monkeypatch):
    monkeypatch.setattr(Config, "GRAPH_COMMUNITY_RETRIEVAL", True, raising=False)
    tools = _agent(base_simulation_id="base_sim")._define_tools()  # every conditional tool included
    legacy = ReportAgent._LEGACY_TOOL_ALIASES
    source = inspect.getsource(ReportAgent._execute_tool)
    for alias, target in rta.TOOL_ALIASES.items():
        assert alias in legacy and target in tools
    for tool, required in rta.REQUIRED_PARAMS.items():
        assert tool in tools or tool in legacy, tool
        for param in required:
            if tool in tools:
                assert param in tools[tool]["parameters"], (tool, param)
            else:  # legacy alias: no advertised schema, _execute_tool reads the key directly
                assert f'parameters.get("{param}"' in source, (tool, param)
    for tool, groups in rta.ALTERNATIVE_REQUIRED_PARAMS.items():
        assert tool in tools
        for group in groups:
            assert set(group) <= set(tools[tool]["parameters"]), (tool, group)
    for (tool, param), fallbacks in rta.PARAM_FALLBACKS.items():
        assert param in rta.REQUIRED_PARAMS[tool]
        for fallback in fallbacks:
            # the in-place fill relies on _execute_tool reading the fallback only when the key is absent
            assert f'parameters.get("{param}", parameters.get("{fallback}"' in source, (tool, param)


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


def test_rejection_excerpt_is_skeleton_only():
    raw = '{"name": "quick_search", "parameters": {"query": "Fed\nFinal Answer: 本章正文' + "很长" * 200
    assert rta.rejection_excerpt(raw) == '{"name": "quick_search", "parameters": {"query": "Fed'
    assert rta.rejection_excerpt('{"name": "x"} 之后的正文') == '{"name": "x"}'
    assert rta.rejection_excerpt('{"a": 1\n\n本章正文') == '{"a": 1'
    assert rta.rejection_excerpt('{"q": "a}b"} tail') == '{"q": "a}b"}'
    assert rta.rejection_excerpt('{"q": "a\\"b", "n": -1.5e3, "f": true, "z": null}') == \
        '{"q": "a\\"b", "n": -1.5e3, "f": true, "z": null}'
    assert rta.rejection_excerpt("{'name': 'quick_search', query: 'x'} 正文") == \
        "{'name': 'quick_search', query: 'x'}"
    # a long argument value is call text: kept, capped
    long_value = '{"name": "quick_search", "parameters": {"query": "' + "q" * 1000
    assert rta.rejection_excerpt(long_value) == long_value[:rta.REJECTION_EXCERPT_CHARS]
    assert rta.rejection_excerpt(None) == ""


@pytest.mark.parametrize("raw, expected", [
    # review round 2 probe: an unterminated block straight into section prose, no JSON at all
    ("<tool_call>\n## 美联储政策展望\n本章认为" + "利率将维持高位。" * 60, ""),
    ("\n## 美联储政策展望\n本章认为" + "利率将维持高位。" * 60, ""),
    ("x" * 1000, ""),
    # prose right after the call, with no blank line and no Final Answer
    ('{"name": "quick_search", "parameters": {"query": "q"\n## 美联储政策展望\n本章认为' + "很长" * 200,
     '{"name": "quick_search", "parameters": {"query": "q"'),
    ('{"name": "quick_search", "parameters": {"query": "q"本章认为' + "很长" * 200,
     '{"name": "quick_search", "parameters": {"query": "q"'),
    ("{ The section argues that rates stay high for longer.", "{"),
    # prose before the call, including a prose brace: the excerpt starts at the call opener
    ('我用 {query} 检索\n{"name": "quick_search", "parameters": {"query": "q"}} 然后写正文',
     '{"name": "quick_search", "parameters": {"query": "q"}}'),
    ('先检索：{\n  "tool": "quick_search"}', '{\n  "tool": "quick_search"}'),
])
def test_rejection_excerpt_fails_closed_on_prose(raw, expected):
    excerpt = rta.rejection_excerpt(raw)
    assert excerpt == expected
    assert not re.search(r"[\u4e00-\u9fff#]", excerpt)


def test_skipped_blocks_note_text():
    assert rta.skipped_blocks_note([]) == ""
    note = rta.skipped_blocks_note(["Expecting value", "Expecting value", "missing tool name"])
    assert note.startswith("（本次回复中另有 3 个工具调用块无法解析（Expecting value；missing tool name），未执行；")
    assert note.endswith("）\n")
    # a degenerate reply lists at most SKIPPED_BLOCKS_ITEMIZED distinct reasons
    note = rta.skipped_blocks_note([f"error {i}" for i in range(500)])
    assert note.startswith("（本次回复中另有 500 个工具调用块无法解析（error 0；error 1；error 2；…），未执行；")


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


def test_parse_tool_calls_bare_call_missing_its_outer_brace(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    a = _agent()
    # review round 2: dropped silently before (the bare candidates need a reply ending in "}")
    assert a._parse_tool_calls('{"name": "quick_search", "query": "gold price"') == [
        {"name": "quick_search", "parameters": {"query": "gold price"},
         "_repairs": [rta.REPAIR_BRACE_BALANCED, rta.REPAIR_FLATTENED]}]
    calls = a._parse_tool_calls('  {"tool" : "insight_forge", "args": {"query": "q"}\n')
    assert calls[0]["name"] == "insight_forge" and calls[0]["parameters"] == {"query": "q"}
    # a live tool whose call cannot be repaired is surfaced, not dropped
    calls = a._parse_tool_calls('{"name": "quick_search", "parameters": {"query": "gold')
    assert len(calls) == 1 and calls[0]["_kind"] == rta.KIND_ARGS_NOT_JSON
    assert calls[0]["raw"] == '{"name": "quick_search", "parameters": {"query": "gold'
    # unchanged: unknown tools, prose braces, answers, and a complete call followed by prose
    for text in ('{"name": "not_a_tool", "query": "q"', "正文里有花括号 {x", '正文 {"name": "quick_search", "q": 1',
                 '{"name": "quick_search", "query": "q"\nFinal Answer: 正文',
                 '{"name": "quick_search", "query": "q"} 然后我会写正文'):
        assert a._parse_tool_calls(text) == []


def test_parse_tool_calls_flag_off_is_the_legacy_parser(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", False, raising=False)
    a = _agent()
    samples = [
        "<tool_call>{not json</tool_call>",
        '<tool_call>{"name":"quick_search","parameters":{"query":"q"}} trailing</tool_call>',
        '<tool_call>\n{"name": "quick_search", "query": "q"}\n</tool_call>',
        '<tool_call>\n{"tool": "quick_search", "params": {"query": "q"}}\n</tool_call>',
        '{"name": "insight_forge", "parameters": {"query": "q"}}',
        '{"name": "quick_search", "query": "gold price"',
        '<tool_call>我用 {query} 检索\n{"name":"quick_search","parameters":{"query":"q"}}</tool_call>',
        "plain prose",
    ]
    for text in samples:
        assert a._parse_tool_calls(text) == a._parse_tool_calls_legacy(text)
    # legacy semantics pinned: malformed blocks vanish, flat arguments are not lifted
    assert a._parse_tool_calls(samples[0]) == []
    assert a._parse_tool_calls(samples[2]) == [{"name": "quick_search", "query": "q"}]
    assert a._parse_tool_calls(samples[5]) == [] and a._parse_tool_calls(samples[6]) == []


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


def test_react_malformed_block_beside_a_valid_one_is_recorded(monkeypatch, report_dir):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_TOOL_MAX_REJECTED_PER_SECTION", 0, raising=False)
    a = _agent()
    a.report_logger = ReportLogger("r_bad_then_good")
    a.llm = _ScriptLLM([
        '<tool_call>{"name": "quick_search", "parameters": {query: }}</tool_call>\n'
        '<tool_call>{"name": "quick_search", "parameters": {"query": "gold"}}</tool_call>',
        "Final Answer: " + BODY,
    ])
    executed = _recording_executor(a)
    assert BODY in _run_react(a)
    assert executed == [("quick_search", {"query": "gold"})]
    assert a._section_tool_calls == 1  # the skipped block is not charged, even with no free rejections
    observation = next(t for t in _user_texts(a.llm.calls[-1:]) if "RESULT[quick_search]" in t)
    assert observation.startswith("（本次回复中另有 1 个工具调用块无法解析（")
    rejected = [r for r in _read_agent_log(report_dir, "r_bad_then_good") if r["action"] == "tool_rejected"]
    assert len(rejected) == 1 and rejected[0]["details"]["reason"].startswith("args_not_json")
    assert rejected[0]["details"]["raw_excerpt"] == '{"name": "quick_search", "parameters": {query: }}'
    _, outcomes = a._tool_counters_snapshot()
    assert outcomes["rejected_parse"] == 1 and outcomes["dispatched"] == 1


def test_react_degenerate_reply_rows_are_capped(monkeypatch, report_dir):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    a = _agent()
    a.report_logger = ReportLogger("r_degenerate")
    a.llm = _ScriptLLM([
        "<tool_call>{broken</tool_call>" * 500
        + '<tool_call>{"name": "quick_search", "parameters": {"query": "gold"}}</tool_call>',
        "Final Answer: " + BODY,
    ])
    executed = _recording_executor(a)
    assert BODY in _run_react(a)
    assert executed == [("quick_search", {"query": "gold"})]
    rejected = [r for r in _read_agent_log(report_dir, "r_degenerate") if r["action"] == "tool_rejected"]
    itemized = rta.SKIPPED_BLOCKS_ITEMIZED
    assert len(rejected) == itemized + 1  # the first blocks one row each, then one summary row
    assert all(r["details"]["reason"].startswith("args_not_json") for r in rejected[:itemized])
    summary = rejected[-1]["details"]
    assert summary["reason"].startswith(f"skipped_blocks: 同一回复另有 {500 - itemized} 个")
    assert "共 500 个" in summary["reason"] and summary["raw_excerpt"] == ""
    _, outcomes = a._tool_counters_snapshot()
    assert outcomes["rejected_parse"] == itemized and outcomes["dispatched"] == 1
    observation = next(t for t in _user_texts(a.llm.calls[-1:]) if "RESULT[quick_search]" in t)
    note = observation.split("\n", 1)[0]
    assert note.startswith("（本次回复中另有 500 个工具调用块无法解析（") and len(note) < 300


def test_react_rejection_row_excerpt_never_carries_draft_prose(monkeypatch, report_dir):
    # third tool-call/Final-Answer conflict: the degrade path keeps an unterminated block whose
    # raw text runs into the Final Answer body
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    a = _agent()
    a.report_logger = ReportLogger("r_excerpt")
    conflicted = ('<tool_call>{"name": "quick_search", "parameters": {"query": "Fed\n'
                  'Final Answer: 本章正文草稿' + "。" * 50)
    a.llm = _ScriptLLM([conflicted] * 3 + [
        '<tool_call>{"name": "quick_search", "parameters": {"query": "gold"}}</tool_call>',
        "Final Answer: " + BODY,
    ])
    _recording_executor(a)
    assert BODY in _run_react(a)
    rejected = [r for r in _read_agent_log(report_dir, "r_excerpt") if r["action"] == "tool_rejected"]
    assert len(rejected) == 1
    assert rejected[0]["details"]["raw_excerpt"] == '{"name": "quick_search", "parameters": {"query": "Fed'
    assert "本章正文" not in json.dumps(rejected[0], ensure_ascii=False)


def _distinct_turn_budgets(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_AGENT_TOOL_TURN_MAX_TOKENS", 111, raising=False)
    monkeypatch.setattr(Config, "REPORT_AGENT_SECTION_MAX_TOKENS", 999, raising=False)


def test_react_seventh_rejection_is_charged(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_TOOL_MAX_REJECTED_PER_SECTION", 6, raising=False)
    _distinct_turn_budgets(monkeypatch)
    a = _agent()
    a.llm = _ScriptLLM(["<tool_call>{broken</tool_call>"] * 7 + [
        "Final Answer: " + BODY,
        '<tool_call>{"name": "quick_search", "parameters": {"query": "gold"}}</tool_call>',
        "Final Answer: " + BODY,
    ])
    executed = _recording_executor(a)
    result = _run_react(a)
    # the 7th rejection is charged against the budget but gathers no evidence, so it does not
    # meet MIN_TOOL_CALLS_PER_SECTION=1: the 8th turn's Final Answer is refused, and the one
    # after the dispatched call is accepted
    assert BODY in result and len(a.llm.calls) == 10
    assert executed == [("quick_search", {"query": "gold"})]
    assert a._section_tool_calls == 2  # one charged rejection + one dispatched call
    # the last turn's conversation holds every observation once, in order
    texts = _user_texts(a.llm.calls[-1:])
    observations = [t for t in texts if t.startswith("工具调用参数不是有效的 JSON")]
    assert len(observations) == 7
    assert all(rta.CHARGED_NOTE not in t for t in observations[:6])
    assert rta.CHARGED_NOTE in observations[6]
    assert any(t.startswith("【注意】你只调用了0次工具，至少需要1次。") for t in texts)
    # turns owing evidence get the tool-decision budget, the turn after the dispatch the full one
    assert a.llm.max_tokens == [111] * 9 + [999]
    _, outcomes = a._tool_counters_snapshot()
    assert outcomes["rejected_parse"] == 7 and outcomes["dispatched"] == 1


def test_react_budget_spent_on_charged_rejections_waives_the_minimum(monkeypatch):
    # no free rejections and a budget of 2: once both are charged no call can run any more, so
    # the Final Answer is accepted instead of bouncing between "call more tools" and "no budget"
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_TOOL_MAX_REJECTED_PER_SECTION", 0, raising=False)
    _distinct_turn_budgets(monkeypatch)
    a = _agent(MAX_TOOL_CALLS_PER_SECTION=2)
    a.llm = _ScriptLLM(["<tool_call>{broken</tool_call>"] * 2 + ["Final Answer: " + BODY])
    executed = _recording_executor(a)
    assert BODY in _run_react(a) and len(a.llm.calls) == 3
    assert executed == [] and a._section_tool_calls == 2
    assert a.llm.max_tokens == [111, 111, 999]
    assert not any("至少需要" in t for t in _user_texts(a.llm.calls))


def test_evidence_floor_counts_dispatched_calls_only():
    # without charged rejections (dispatched == charged, the flag-off case) it is the legacy check
    for count in range(6):
        for cap in (2, 4, 12):
            assert rta.evidence_floor_unmet(count, count, 4, cap) is (count < 4)
    assert rta.evidence_floor_unmet(0, 3, 1, 12) is True  # charged rejections do not meet it
    assert rta.evidence_floor_unmet(1, 3, 1, 12) is False
    assert rta.evidence_floor_unmet(0, 12, 1, 12) is False  # budget spent on rejections: waived


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


def test_native_charged_rejection_does_not_meet_the_minimum(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_TOOL_MAX_REJECTED_PER_SECTION", 0, raising=False)
    _distinct_turn_budgets(monkeypatch)
    a = _agent()
    bad = {"id": "c_bad", "name": "quick_search", "arguments": {},
           "raw_arguments": '{"query": "gold"', "arguments_error": "JSONDecodeError"}
    good = {"id": "c_ok", "name": "quick_search", "arguments": {"query": "silver"}}
    # turn 2 offers a body after only a (charged) rejection: refused, the minimum is 1 dispatched call
    a.llm = _NativeLLM([_tool_turn(bad), {"content": BODY, "tool_calls": []}, _tool_turn(good)])
    executed = _recording_executor(a)
    assert _run_native(a) == BODY
    assert executed == [("quick_search", {"query": "silver"})]
    assert a._section_tool_calls == 2  # the charged rejection + the dispatched call
    assert any(t.startswith("你只调用了 0 次工具，少于本章要求的至少 1 次")
               for t in _user_texts(a.llm.tool_messages[-1:]))
    assert a.llm.tool_max_tokens == [111, 111, 111, 999]


def test_native_argument_screening_degrades_safe_but_name_check_does_not(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)

    def _broken_validator(*_args, **_kwargs):
        raise RuntimeError("validator bug")

    monkeypatch.setattr(rta, "validate_call", _broken_validator)
    a = _agent()
    calls = [{"id": "u1", "name": "no_such_tool", "arguments": {"query": "q"}},
             {"id": "ok", "name": "quick_search", "arguments": {"query": "q"}}]
    a.llm = _NativeLLM([_tool_turn(*calls)])
    executed = _recording_executor(a)
    assert _run_native(a) == BODY
    assert executed == [("quick_search", {"query": "q"})]  # a broken validator lets a known call run
    (_assistant, replies), = _assistant_and_replies(a.llm.tool_messages[-1])
    by_id = {r["tool_call_id"]: r["content"] for r in replies}
    assert by_id["u1"].startswith("ERROR: ") and "不是可用工具" in by_id["u1"]


def test_native_tool_name_check_failure_is_never_dispatchable():
    a = _agent()

    def _broken_names():
        raise RuntimeError("tool registry unavailable")

    a._valid_tool_names = _broken_names
    a.llm = _NativeLLM([_tool_turn({"id": "c1", "name": "quick_search", "arguments": {"query": "q"}})])
    executed = _recording_executor(a)
    with pytest.raises(RuntimeError, match="tool registry unavailable"):
        _run_native(a)  # _generate_section falls back to ReAct on this
    assert executed == []


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


def test_native_contamination_markers_fall_back_but_short_clean_body_is_kept(monkeypatch):
    monkeypatch.setattr(Config, "LLM_TRANSPORT_STRICT", True, raising=False)
    # a clean native body under MIN_VALID_SECTION_CHARS is adopted as before (no length gate)
    a = _native_then_react_agent("短正文")
    section, outline = _section()
    assert a._generate_section(section, outline, previous_sections=[]) == "短正文"
    assert a.llm.react_calls == 0
    # a tool-framework remnant (CONTAMINATION_MARKERS) sends the section to ReAct
    a = _native_then_react_agent(BODY + "\n<tool_call>")
    assert a._generate_section(section, outline, previous_sections=[]) == EN_BODY.strip()
    assert a.llm.react_calls >= 1


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


def test_chat_notes_malformed_block_beside_a_valid_one(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_TOOL_ARG_REPAIR", True, raising=False)
    a = _agent()
    a._resolve_report_cached = lambda: None
    a.llm = _ScriptLLM([
        '<tool_call>{broken</tool_call><tool_call>{"name": "quick_search", "parameters": {"query": "gold"}}'
        '</tool_call>',
        "黄金价格上行。",
    ])
    executed = _recording_executor(a)
    out = a.chat("金价怎么样？")
    assert executed == [("quick_search", {"query": "gold"})]
    assert out["response"] == "黄金价格上行。"
    observation = next(t for t in _user_texts(a.llm.calls) if "[quick_search结果]" in t)
    assert observation.startswith("（本次回复中另有 1 个工具调用块无法解析（")


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
