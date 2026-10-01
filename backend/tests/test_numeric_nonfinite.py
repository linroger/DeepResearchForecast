"""Offline tests for INFRA-4: non-finite number guards and status-first LLM error classification.

Covers app/utils/numeric.py (find_nonfinite / dumps_strict / null_nonfinite / decode hooks),
utils/atomic.write_json_atomic(allow_nan=False), llm_client's strict-number JSON parsing and the
chat_json repair turn it feeds (LLM_JSON_STRICT_NUMBERS), the v3 research gateway's strict decoder
(RESEARCH_JSON_STRICT_NUMBERS) and its forwarding to the v3 child, report_agent's forecast.json /
market_comparison.json writes and spine pinning (ARTIFACT_STRICT_JSON), _classify_llm_error and
its consumers (LLM_ERROR_CLASSIFY_STATUS_FIRST), the Polymarket 200-body schema record, and the
backfill_report_visuals rewrite of forecast.json / market_comparison.json.
Every knob is also exercised off (legacy behaviour). No network, no real LLM.
"""

import json
import math
import os
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.config import Config
from app.config_audit import extract_knobs
from app.services import forecast_extractor as fe
from app.services import pipeline_orchestrator as po
from app.services import report_agent as ra
from app.services.report_agent import ReportAgent, ReportManager
from app.utils import llm_client as lc
from app.utils import numeric
from app.utils import prediction_markets as pm
from app.utils import telemetry as tel
from app.utils.atomic import write_json_atomic
from app.utils.numeric import NonFiniteJSONError
from scripts import backfill_report_visuals as bf
from tests.test_research_gateway import FakeModel, ai, gateway, msgs, rg

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_KNOBS = ("LLM_JSON_STRICT_NUMBERS", "LLM_ERROR_CLASSIFY_STATUS_FIRST", "ARTIFACT_STRICT_JSON",
          "RESEARCH_JSON_STRICT_NUMBERS")
_NAN, _INF = float("nan"), float("inf")
# A 2056 usage-cap notice that the legacy auth wording check also reads as a 401.
_USAGE_CAP_401 = "Error code: 401 - usage limit exceeded (2056)"


def _raise_on_constant(name):
    raise ValueError(f"non-standard JSON constant {name}")


def _strict_load(text):
    """What a browser's JSON.parse accepts: no NaN / Infinity."""
    return json.loads(text, parse_constant=_raise_on_constant)


# ------------------------------------------------------------------ numeric module
def test_find_nonfinite_names_json_paths():
    assert numeric.find_nonfinite({"a": [1, _NAN], "b": {"c": _INF}}) == ["$.a[1]", "$.b.c"]
    assert numeric.find_nonfinite(({"x": -_INF}, [0.5, (1, _NAN)])) == ["$[0].x", "$[1][1][1]"]
    assert numeric.find_nonfinite({"a b": _NAN, "中文": _INF}) == ['$["a b"]', '$["中文"]']
    assert numeric.find_nonfinite({"ok": [0, 1.5, "NaN", None, True]}) == []
    cyclic = {"x": _NAN}
    cyclic["self"] = cyclic
    assert numeric.find_nonfinite(cyclic) == ["$.x"]


def test_is_finite_number_excludes_bools_and_nonfinite():
    assert [numeric.is_finite_number(v) for v in (0, 7, 10 ** 400, 1.5, -0.0)] == [True] * 5
    assert [numeric.is_finite_number(v) for v in (True, False, _NAN, _INF, -_INF, "1", None)] \
        == [False] * 7
    # bools are never numbers, so a True leaf is not reported as non-finite either
    assert numeric.find_nonfinite([True, False]) == []


def test_dumps_strict_raises_with_paths_and_is_byte_identical_for_finite():
    with pytest.raises(NonFiniteJSONError) as info:
        numeric.dumps_strict({"p": _NAN, "q": [1, _INF]})
    assert info.value.paths == ["$.p", "$.q[1]"]
    assert "$.p" in str(info.value) and "$.q[1]" in str(info.value)
    assert isinstance(info.value, ValueError)
    many = {f"k{i}": _NAN for i in range(12)}
    with pytest.raises(NonFiniteJSONError) as info:
        numeric.dumps_strict(many)
    assert len(info.value.paths) == 12 and "(+2 more)" in str(info.value)
    finite = {"headline": "预测", "p": 0.35, "n": [1, 2.5e-7, -0.0], "t": (1, 2), "b": True}
    assert numeric.dumps_strict(finite, ensure_ascii=False, indent=2) \
        == json.dumps(finite, ensure_ascii=False, indent=2)
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(ValueError) as info:
        numeric.dumps_strict(cyclic)
    assert not isinstance(info.value, NonFiniteJSONError)  # a circular reference stays itself


def test_null_nonfinite_copies_and_reports_paths():
    original = {"scenarios": [{"p": 0.4}, {"p": _NAN}], "q": (_INF, 2), "keep": "x"}
    cleaned, paths = numeric.null_nonfinite(original)
    assert paths == ["$.scenarios[1].p", "$.q[0]"]
    assert cleaned == {"scenarios": [{"p": 0.4}, {"p": None}], "q": (None, 2), "keep": "x"}
    assert math.isnan(original["scenarios"][1]["p"]) and original["q"][0] == _INF  # untouched
    assert numeric.null_nonfinite({"a": 1}) == ({"a": 1}, [])


def test_null_nonfinite_turns_nonfinite_keys_into_their_json_text():
    original = {_NAN: 1, "b": {-_INF: _NAN}}
    cleaned, paths = numeric.null_nonfinite(original)
    assert cleaned == {"NaN": 1, "b": {"-Infinity": None}}
    assert paths == numeric.find_nonfinite(original) == ['$.b["-Infinity"]']
    assert numeric.dumps_strict(cleaned) == '{"NaN": 1, "b": {"-Infinity": null}}'
    key_only = {_INF: "x"}
    with pytest.raises(NonFiniteJSONError):
        numeric.dumps_strict(key_only)
    # a key-only fix keeps the text json writes by default
    assert numeric.dumps_strict(numeric.null_nonfinite(key_only)[0]) == json.dumps(key_only)


def test_decode_hooks_reject_nonfinite_tokens():
    hooks = {"parse_constant": numeric.reject_nonfinite_constant,
             "parse_float": numeric.parse_finite_float}
    for text in ('{"p": NaN}', '{"p": Infinity}', '{"p": -Infinity}', '{"p": 1e999}'):
        with pytest.raises(json.JSONDecodeError, match="non-finite constant"):
            json.loads(text, **hooks)
    assert json.loads('{"p": 0.25, "n": 1e-3, "i": 10}', **hooks) == {"p": 0.25, "n": 0.001, "i": 10}


# ------------------------------------------------------------------ atomic
def test_write_json_atomic_strict_raises_and_leaves_no_file(tmp_path):
    path = tmp_path / "out" / "artifact.json"
    with pytest.raises(NonFiniteJSONError) as info:
        write_json_atomic(str(path), {"x": _NAN}, allow_nan=False)
    assert "$.x" in str(info.value) and str(path) in str(info.value)
    assert info.value.paths == ["$.x"]
    assert not path.exists()
    assert not any(tmp_path.rglob(".tmp-*"))
    # default allow_nan=True keeps the legacy write; finite strict writes are unchanged
    write_json_atomic(str(path), {"x": _NAN})
    assert "NaN" in path.read_text(encoding="utf-8")
    write_json_atomic(str(path), {"x": 0.5, "s": "中"}, allow_nan=False)
    assert path.read_text(encoding="utf-8") == json.dumps({"x": 0.5, "s": "中"},
                                                          ensure_ascii=False, indent=2)
    cyclic = {}
    cyclic["c"] = cyclic
    with pytest.raises(ValueError) as info:
        write_json_atomic(str(tmp_path / "cyc.json"), cyclic, allow_nan=False)
    assert not isinstance(info.value, NonFiniteJSONError)


# ------------------------------------------------------------------ llm_client parsing
@pytest.mark.parametrize("text", ['{"p": NaN}', '{"p": 1e999}', '{"p": -Infinity}',
                                  'Here: {"p": Infinity} done', '```json\n{"a": [1, NaN]}\n```',
                                  '{"a": 1, "b": NaN'])
def test_parse_json_response_rejects_nonfinite_under_flag(monkeypatch, text):
    monkeypatch.setattr(Config, "LLM_JSON_STRICT_NUMBERS", True, raising=False)
    sentinel = object()
    assert lc.LLMClient._parse_json_response_ex(text, unparsed=sentinel) == (sentinel, False)
    assert lc.LLMClient._parse_json_response(text) is None


def test_parse_json_response_flag_off_accepts_nan(monkeypatch):
    monkeypatch.setattr(Config, "LLM_JSON_STRICT_NUMBERS", False, raising=False)
    value, repaired = lc.LLMClient._parse_json_response_ex('{"p": NaN, "q": 1e999}')
    assert math.isnan(value["p"]) and value["q"] == _INF and repaired is False


@pytest.mark.parametrize("text", ['{"p": 0.35, "s": "x"}', '```json\n{"a": [1, 2.5]}\n```',
                                  'Sure: {"a": {"b": 1e-3}} ok', '{"a": [1, {"b": "c"',
                                  '{"a": 1,', 'null', '[1, 2]', 'garbage'])
def test_parse_json_response_finite_replies_identical_both_ways(monkeypatch, text):
    results = []
    for flag in (True, False):
        monkeypatch.setattr(Config, "LLM_JSON_STRICT_NUMBERS", flag, raising=False)
        results.append(lc.LLMClient._parse_json_response_ex(text, unparsed="UNPARSED"))
    assert results[0] == results[1]


# ------------------------------------------------------------------ chat_json repair turn
def _resp(content, finish="stop"):
    message = SimpleNamespace(content=content, tool_calls=[])
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)],
                           usage=None)


class _Transport:
    """Fake OpenAI client serving scripted replies (the last one repeats); records kwargs."""

    def __init__(self, *contents):
        self.responses = [_resp(c) for c in contents]
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses[min(len(self.calls), len(self.responses)) - 1]


@pytest.fixture
def minimax_client(monkeypatch):
    """An LLMClient on a fake minimax transport, cache and telemetry isolated."""
    for name in ("LLM_FALLBACK_PROVIDER", "LLM_FALLBACK_MODEL", "LLM_FALLBACK_BASE_URL",
                 "LLM_FALLBACK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(lc, "_retry_delay", lambda exc, attempt: 0.0)
    for name, value in (("LLM_PROVIDER", "minimax"), ("LLM_MODEL_NAME", "MiniMax-M3"),
                        ("LLM_API_KEY", "sk-test"), ("LLM_BASE_URL", "http://127.0.0.1:1/v1"),
                        ("LLM_CACHE_ENABLED", True), ("LLM_TELEMETRY_ENABLED", True),
                        ("LLM_JSON_REPAIR_TURN", True), ("LLM_TIERED_ROUTING", False),
                        ("LLM_RUN_BUDGET_TOKENS", 0), ("LLM_RUN_BUDGET_USD", 0.0)):
        monkeypatch.setattr(Config, name, value, raising=False)
    monkeypatch.setattr(tel.LLMCache, "_store", {})
    monkeypatch.setattr(tel.LLMCache, "_order", [])
    transport = _Transport('{"p": 0.4}')
    monkeypatch.setattr(lc.LLMClient, "_build_openai_client",
                        staticmethod(lambda provider, api_key, base_url: transport))
    lc._CB_STATE.clear()
    tel.LLMMeter.reset("infra4-run")
    tel.set_run_context("infra4-run", "report")
    yield lc.LLMClient(provider="minimax"), transport
    tel.set_run_context(None)
    tel.LLMMeter.reset("infra4-run")
    lc._CB_STATE.clear()


def _json_msgs(tag):
    return [{"role": "user", "content": f"infra4-{tag}: return JSON"}]


def test_nonfinite_reply_triggers_the_repair_turn(monkeypatch, minimax_client):
    monkeypatch.setattr(Config, "LLM_JSON_STRICT_NUMBERS", True, raising=False)
    client, transport = minimax_client
    transport.responses = [_resp('{"p": NaN}'), _resp('{"p": 0.4}')]
    messages = _json_msgs("nan")
    assert client.chat_json(messages) == {"p": 0.4}
    first, second = transport.calls
    assert second["messages"] == messages + [
        {"role": "assistant", "content": '{"p": NaN}'},
        {"role": "user", "content": lc._JSON_REPAIR_NOTE.format(reason=lc._JSON_MISS_NONFINITE)},
    ]
    assert "NaN or Infinity is not a JSON number" in second["messages"][-1]["content"]
    structured = tel.LLMMeter.snapshot("infra4-run")["structured_outputs"]["chat_json"]
    assert structured["repaired"] == 1 and structured["failed"] == 0


def test_overflowing_float_twice_fails_closed(monkeypatch, minimax_client):
    monkeypatch.setattr(Config, "LLM_JSON_STRICT_NUMBERS", True, raising=False)
    client, transport = minimax_client
    transport.responses = [_resp('{"p": 1e999}')]
    with pytest.raises(ValueError, match="NaN or Infinity"):
        client.chat_json(_json_msgs("inf"))
    assert len(transport.calls) == 2


def test_nonfinite_reply_accepted_with_flag_off(monkeypatch, minimax_client):
    monkeypatch.setattr(Config, "LLM_JSON_STRICT_NUMBERS", False, raising=False)
    client, transport = minimax_client
    transport.responses = [_resp('{"p": NaN}')]
    value = client.chat_json(_json_msgs("nan-off"))
    assert math.isnan(value["p"]) and len(transport.calls) == 1


def test_plain_invalid_json_keeps_the_generic_reason(monkeypatch, minimax_client):
    monkeypatch.setattr(Config, "LLM_JSON_STRICT_NUMBERS", True, raising=False)
    client, transport = minimax_client
    transport.responses = [_resp("not json"), _resp('{"ok": 1}')]
    assert client.chat_json(_json_msgs("garbage")) == {"ok": 1}
    assert transport.calls[1]["messages"][-1]["content"] \
        == lc._JSON_REPAIR_NOTE.format(reason=lc._JSON_MISS_INVALID)


# ------------------------------------------------------------------ FU-12 hostile replies
# Past the int-string digit limit / the decoder's recursion limit: the reply takes the
# repair turn instead of raising (see test_json_parse_never_raises.py).
_FU12_HOSTILE = {"huge_int": '{"p": ' + "9" * 5000 + "}",
                 "deep_array": '{"p": ' + "[" * 100_000 + "]" * 100_000 + "}"}


@pytest.mark.parametrize("name", ["huge_int", "deep_array"])
def test_chat_json_takes_the_repair_turn_on_a_hostile_reply(monkeypatch, minimax_client, name):
    monkeypatch.setattr(Config, "LLM_JSON_STRICT_NUMBERS", True, raising=False)
    client, transport = minimax_client
    transport.responses = [_resp(_FU12_HOSTILE[name]), _resp('{"p": 0.4}')]
    assert client.chat_json(_json_msgs(f"fu12-{name}")) == {"p": 0.4}
    assert len(transport.calls) == 2
    assert transport.calls[1]["messages"][-1]["content"] \
        == lc._JSON_REPAIR_NOTE.format(reason=lc._JSON_MISS_INVALID)


def test_chat_json_fails_closed_with_a_value_error_on_repeated_hostile_replies(monkeypatch,
                                                                                minimax_client):
    monkeypatch.setattr(Config, "LLM_JSON_STRICT_NUMBERS", True, raising=False)
    client, transport = minimax_client
    transport.responses = [_resp(_FU12_HOSTILE["deep_array"])]
    with pytest.raises(ValueError):
        client.chat_json(_json_msgs("fu12-stubborn"))
    assert len(transport.calls) == 2


# ------------------------------------------------------------------ research gateway
def test_gateway_parse_json_object_strict_by_default(monkeypatch):
    monkeypatch.delenv("RESEARCH_JSON_STRICT_NUMBERS", raising=False)
    for text in ('{"p": NaN}', '{"p": 1e999}', 'Plan: {"kiqs": [{"w": -Infinity}]}'):
        assert rg.parse_json_object(text) is None
    assert rg.parse_json_object('x {"a": NaN, "b": 1}', ("a",)) is None
    assert rg._describe_json_failure('{"p": NaN}', ("p",), False) \
        == "NaN or Infinity is not a JSON number"
    # strict=False control-character tolerance and finite numbers are unchanged
    assert rg.parse_json_object('{"t": "line\nbreak", "p": 0.5, "e": 1e-3}') \
        == {"t": "line\nbreak", "p": 0.5, "e": 0.001}
    assert rg._describe_json_failure("no object here", (), False) == "no JSON object found"


def test_gateway_parse_json_object_accepts_nan_when_disabled(monkeypatch):
    monkeypatch.setenv("RESEARCH_JSON_STRICT_NUMBERS", "false")
    value = rg.parse_json_object('{"p": NaN, "q": 1e999}', ("p",))
    assert math.isnan(value["p"]) and value["q"] == _INF
    assert rg._describe_json_failure('{"p": 1', ("p",), True) \
        == "reply was truncated before the JSON object closed"


@pytest.mark.parametrize("text", ['{"a": 1, "b": [1, 2.5]}', '```json\n{"k": {"x": "y"}}\n```',
                                  'pre {n} [S3] {"a": 1,}', '{"a": [{"x": 1}, {"},{"y": 2}]}',
                                  '{"a": {"b": 1, "c": [1, 2'])
def test_gateway_finite_replies_identical_both_ways(monkeypatch, text):
    results = []
    for flag in ("true", "false"):
        monkeypatch.setenv("RESEARCH_JSON_STRICT_NUMBERS", flag)
        results.append(rg.parse_json_object(text))
    assert results[0] == results[1]


def test_gateway_json_retry_names_the_nonfinite_number(monkeypatch):
    monkeypatch.delenv("RESEARCH_JSON_STRICT_NUMBERS", raising=False)
    model = FakeModel([ai('{"kiqs": [], "p": NaN}'), ai('{"kiqs": [], "p": 0.3}')])
    gw, _plog = gateway(model)
    notes = []
    obj = gw.json(lambda note: notes.append(note) or msgs(f"task {note or ''}"),
                  label="plan", required_keys=("kiqs", "p"))
    assert obj == {"kiqs": [], "p": 0.3}
    assert notes[1].startswith(
        "Your previous reply was not valid JSON (NaN or Infinity is not a JSON number).")
    # a model that keeps answering NaN fails closed: JsonUnparseable, never a NaN value
    stubborn = FakeModel([ai('{"kiqs": [], "p": NaN}'), ai('{"kiqs": [], "p": 1e999}')])
    gw2, _plog2 = gateway(stubborn)
    with pytest.raises(rg.JsonUnparseable):
        gw2.json(lambda note: msgs(f"task {note or ''}"), label="plan", required_keys=("kiqs",))


_PLAN_KEYS = ("kiqs", "sections", "scenarios")
# Realistic v3 replies nest objects; only one of them holds the NaN.
_NESTED_NAN_PLAN = ('{"kiqs": [{"id": "K1", "question": "q"}], "sections": [{"t": "s"}], '
                    '"scenarios": [{"name": "A", "probability": NaN}]}')
_NONFINITE_REASON = "NaN or Infinity is not a JSON number"


@pytest.mark.parametrize("text, keys", [
    (_NESTED_NAN_PLAN, _PLAN_KEYS),
    ('{"quantitative_facts": [{"value": 1.2}, {"value": NaN}]}', ("quantitative_facts",)),
    ('Gaps: {"follow_ups": [{"q": "a", "w": 0.5}, {"q": "b", "w": Infinity}]}', ("follow_ups",)),
])
def test_gateway_names_the_nonfinite_number_in_nested_replies(monkeypatch, text, keys):
    monkeypatch.delenv("RESEARCH_JSON_STRICT_NUMBERS", raising=False)
    assert rg.parse_json_object(text, keys) is None
    assert rg._describe_json_failure(text, keys, False) == _NONFINITE_REASON
    monkeypatch.setenv("RESEARCH_JSON_STRICT_NUMBERS", "false")
    assert set(keys) <= set(rg.parse_json_object(text, keys))  # legacy: the whole object


def test_gateway_missing_keys_reason_also_names_the_nonfinite_number(monkeypatch):
    monkeypatch.delenv("RESEARCH_JSON_STRICT_NUMBERS", raising=False)
    text = '{"kiqs": [{"id": "K1"}], "scenarios": [{"p": NaN}]}'
    assert rg._describe_json_failure(text, _PLAN_KEYS, False) \
        == "missing keys: sections; " + _NONFINITE_REASON
    assert rg._describe_json_failure('{"kiqs": [{"id": "K1"}]}', _PLAN_KEYS, False) \
        == "missing keys: sections, scenarios"
    monkeypatch.setenv("RESEARCH_JSON_STRICT_NUMBERS", "false")
    assert rg._describe_json_failure(text, _PLAN_KEYS, False) == "missing keys: sections"


def test_gateway_json_retry_names_nan_in_a_nested_plan(monkeypatch):
    monkeypatch.delenv("RESEARCH_JSON_STRICT_NUMBERS", raising=False)
    model = FakeModel([ai(_NESTED_NAN_PLAN), ai(_NESTED_NAN_PLAN.replace("NaN", "0.4"))])
    gw, _plog = gateway(model)
    notes = []
    obj = gw.json(lambda note: notes.append(note) or msgs(f"task {note or ''}"),
                  label="plan", required_keys=_PLAN_KEYS)
    assert obj["scenarios"] == [{"name": "A", "probability": 0.4}]
    assert notes[1] == (f"Your previous reply was not valid JSON ({_NONFINITE_REASON}). "
                        "Reply with ONLY one JSON object with keys: kiqs, sections, scenarios.")
    # the error detail and the progress log name the same cause
    stubborn = FakeModel([ai(_NESTED_NAN_PLAN), ai(_NESTED_NAN_PLAN)])
    gw2, plog2 = gateway(stubborn)
    with pytest.raises(rg.JsonUnparseable) as info:
        gw2.json(lambda note: msgs(f"task {note or ''}"), label="plan", required_keys=_PLAN_KEYS)
    assert info.value.detail == f"plan: {_NONFINITE_REASON}"
    warnings = [line for line in plog2.of("warn") if "JSON attempt" in line]
    assert len(warnings) == 2 and all(f"({_NONFINITE_REASON})" in line for line in warnings)


@pytest.mark.parametrize("text, keys, legacy_keys", [
    ('{"meta": {"n": 1}, "p": NaN}', (), {"meta", "p"}),
    ('{"scenarios": [{"p": NaN}, {"name": "B", "p": 0.5}]}', (), {"scenarios"}),
    ('{"scenarios": [{"p": NaN}, {"name": "B", "p": 0.5}]}', ("name",), {"name", "p"}),
    ('```json\n{"meta": {"n": 1}, "p": NaN}\n```', (), {"meta", "p"}),
])
def test_gateway_never_returns_a_fragment_of_a_rejected_object(monkeypatch, text, keys,
                                                              legacy_keys):
    monkeypatch.delenv("RESEARCH_JSON_STRICT_NUMBERS", raising=False)
    assert rg.parse_json_object(text, keys) is None  # not {"n": 1} / {"name": "B", ...}
    assert rg._describe_json_failure(text, keys, False) == _NONFINITE_REASON
    monkeypatch.setenv("RESEARCH_JSON_STRICT_NUMBERS", "false")
    assert set(rg.parse_json_object(text, keys)) == legacy_keys


def test_gateway_reads_a_separate_object_after_a_rejected_one(monkeypatch):
    monkeypatch.delenv("RESEARCH_JSON_STRICT_NUMBERS", raising=False)
    text = 'Draft {"a": NaN, "m": {"a": 2}} Final {"a": 1}'
    assert rg.parse_json_object(text, ("a",)) == {"a": 1}


def test_research_json_knob_is_forwarded_to_the_v3_child(monkeypatch):
    assert ("RESEARCH_JSON_STRICT_NUMBERS", "bool") in po.RESEARCH_CHILD_V3_KNOBS
    assert ("RESEARCH_JSON_STRICT_NUMBERS", "bool") not in po.RESEARCH_CHILD_KNOBS
    env = {"RESEARCH_JSON_STRICT_NUMBERS": "ambient"}
    po._forward_research_knobs(env, po.RESEARCH_CHILD_V3_KNOBS)
    assert env["RESEARCH_JSON_STRICT_NUMBERS"] == "true"
    monkeypatch.setattr(Config, "RESEARCH_JSON_STRICT_NUMBERS", False, raising=False)
    po._forward_research_knobs(env, po.RESEARCH_CHILD_V3_KNOBS)
    assert env["RESEARCH_JSON_STRICT_NUMBERS"] == "false"


# ------------------------------------------------------------------ report agent
_NAMES = ("Rapid adoption path", "Gradual adoption path", "Other / Status Quo")


def _scenarios(probs):
    return [{"name": name, "probability": p, "summary": f"{name} summary",
             "key_drivers": ["driver"], "resolution_criteria": f"{name} resolves by 2030"}
            for name, p in zip(_NAMES, probs, strict=True)]


def _agent(llm=None):
    agent = ReportAgent.__new__(ReportAgent)
    for key, value in {
        "graph_id": "g1", "simulation_id": "sim1", "llm": llm,
        "simulation_requirement": "Will adoption accelerate?", "situation_brief": "",
        "actors": None, "sources": [], "research_report": "", "output_language": "English",
        "scenario_label": "", "base_simulation_id": None, "_background_block": "",
        "_sources_index": "", "_signal_pack": "", "_market_pack": "", "_forecast_spine": None,
        "_forecast_spine_block": "", "_retrieval_query": None, "_outline_degraded": False,
        "_outline_summary": "", "_section_tool_calls": 0, "report_logger": None,
        "console_logger": None, "tools": {},
    }.items():
        setattr(agent, key, value)
    return agent


@pytest.fixture
def report_env(monkeypatch, tmp_path):
    for name, value in (("UPLOAD_FOLDER", str(tmp_path)),
                        ("FORECAST_LEDGER_DIR", str(tmp_path / "ledger")),
                        ("REPORT_PUBLISH_GATE", False), ("REPORT_REPAIR_PASSES", False),
                        ("REPORT_FORECAST_SELF_CRITIQUE", False),
                        ("REPORT_CRITIQUE_BEFORE_PROSE", False), ("REPORT_FORECAST_LEDGER", False),
                        ("FORECAST_EMIT_BINARY", False), ("ARTIFACT_STRICT_JSON", True)):
        monkeypatch.setattr(Config, name, value, raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    return tmp_path


def _artifact(tmp_path, report_id, name="forecast.json"):
    return tmp_path / "reports" / report_id / name


def test_nonfinite_spine_is_not_pinned_or_written(monkeypatch, report_env):
    spine = {"headline": "h", "horizon": "2030", "confidence": "medium",
             "scenarios": _scenarios([0.5, 0.3, 0.2]), "base_rate_weight": _NAN}
    monkeypatch.setattr(fe, "derive_forecast_spine", lambda llm, **kw: dict(spine))
    agent = _agent()
    agent._derive_and_pin_forecast_spine("report_spine_nan")
    assert agent._forecast_spine is None and agent._forecast_spine_block == ""
    assert not _artifact(report_env, "report_spine_nan").exists()

    monkeypatch.setattr(Config, "ARTIFACT_STRICT_JSON", False, raising=False)
    legacy = _agent()
    legacy._derive_and_pin_forecast_spine("report_spine_legacy")
    assert legacy._forecast_spine is not None and legacy._forecast_spine_block
    assert "NaN" in _artifact(report_env, "report_spine_legacy").read_text(encoding="utf-8")


def test_finite_spine_is_pinned_and_written_strictly(monkeypatch, report_env):
    spine = {"headline": "h", "horizon": "2030", "confidence": "medium",
             "scenarios": _scenarios([0.5, 0.3, 0.2])}
    monkeypatch.setattr(fe, "derive_forecast_spine", lambda llm, **kw: dict(spine))
    agent = _agent()
    agent._derive_and_pin_forecast_spine("report_spine_ok")
    assert agent._forecast_spine["scenarios"] == spine["scenarios"]
    assert _strict_load(_artifact(report_env, "report_spine_ok").read_text(encoding="utf-8")) \
        == agent._forecast_spine


def _post_hoc_forecast():
    forecast = {"headline": "h", "horizon": "2030", "confidence": "medium",
                "scenarios": _scenarios([0.5, 0.3, 0.2]), "quality": {"note": "kept"}}
    forecast["scenarios"][1]["signal_score"] = _NAN
    forecast["quality"]["spread"] = -_INF
    return forecast


def test_final_forecast_json_nulls_nonfinite_leaves(monkeypatch, report_env):
    monkeypatch.setattr(fe, "extract_structured_forecast", lambda *a, **kw: _post_hoc_forecast())
    agent = _agent()
    agent._finalize_structured_forecast("report_final_nan", "# T\n\nBody text.")
    text = _artifact(report_env, "report_final_nan").read_text(encoding="utf-8")
    forecast = _strict_load(text)  # standard JSON: JSON.parse would accept it
    assert "NaN" not in text and "Infinity" not in text
    assert forecast["scenarios"][1]["signal_score"] is None
    assert forecast["quality"]["spread"] is None and forecast["quality"]["note"] == "kept"
    assert forecast["quality"]["nonfinite_nulled"] == ["$.scenarios[1].signal_score",
                                                       "$.quality.spread"]
    assert agent._forecast_spine == forecast  # memory matches disk


def test_final_forecast_json_flag_off_writes_nan(monkeypatch, report_env):
    monkeypatch.setattr(Config, "ARTIFACT_STRICT_JSON", False, raising=False)
    monkeypatch.setattr(fe, "extract_structured_forecast", lambda *a, **kw: _post_hoc_forecast())
    _agent()._finalize_structured_forecast("report_final_legacy", "# T\n\nBody text.")
    forecast = json.loads(_artifact(report_env, "report_final_legacy").read_text(encoding="utf-8"))
    assert math.isnan(forecast["scenarios"][1]["signal_score"])
    assert "nonfinite_nulled" not in forecast["quality"]


def test_finite_forecast_has_no_nonfinite_record(monkeypatch, report_env):
    finite = {"headline": "h", "scenarios": _scenarios([0.5, 0.3, 0.2])}
    monkeypatch.setattr(fe, "extract_structured_forecast", lambda *a, **kw: dict(finite))
    _agent()._finalize_structured_forecast("report_final_ok", "# T\n\nBody text.")
    forecast = _strict_load(_artifact(report_env, "report_final_ok").read_text(encoding="utf-8"))
    assert "nonfinite_nulled" not in forecast.get("quality", {})


def test_market_comparison_json_never_carries_nan(monkeypatch, report_env):
    monkeypatch.setattr(Config, "FORECAST_EMIT_BINARY", True, raising=False)
    monkeypatch.setattr(fe, "extract_structured_forecast",
                        lambda *a, **kw: {"headline": "h", "scenarios": _scenarios([0.5, 0.3, 0.2])})
    binaries = [{"id": f"F{i}", "statement": f"Adoption metric {i} exceeds {i}0% by 2030",
                 "probability": 0.3 + i / 20, "resolution_criteria": "Official index above target",
                 "theme": "adoption", "horizon_year": 2030} for i in range(1, 4)]
    monkeypatch.setattr(fe, "extract_binary_forecasts",
                        lambda *a, **kw: {"binary_forecasts": [dict(b) for b in binaries],
                                          "binary_quality": {}})

    def reconcile(forecast):
        forecast["market_comparison"] = {
            "anchored_count": 1,
            "comparisons": [{"id": "F1", "forecast_prob": 0.35, "market_prob": _NAN,
                             "delta": _INF, "flag": False}]}
        return {}

    monkeypatch.setattr(fe, "reconcile_forecast_contract", reconcile)
    _agent()._finalize_structured_forecast("report_mc_nan", "# T\n\nBody text.")
    mc = _strict_load(_artifact(report_env, "report_mc_nan", "market_comparison.json")
                      .read_text(encoding="utf-8"))
    assert mc["comparisons"][0]["market_prob"] is None and mc["comparisons"][0]["delta"] is None
    assert mc["comparisons"][0]["forecast_prob"] == 0.35
    forecast = _strict_load(_artifact(report_env, "report_mc_nan").read_text(encoding="utf-8"))
    assert forecast["market_comparison"] == mc
    assert forecast["quality"]["nonfinite_nulled"] == [
        "$.market_comparison.comparisons[0].market_prob",
        "$.market_comparison.comparisons[0].delta"]


def test_forecast_artifact_json_is_byte_identical_for_finite_content(monkeypatch):
    finite = {"headline": "中文 headline", "scenarios": _scenarios([0.5, 0.3, 0.2]),
              "binary_forecasts": [{"id": "F1", "probability": 0.42}], "quality": {"n": 3}}
    legacy = json.dumps(finite, ensure_ascii=False, indent=2)
    for flag in (True, False):
        monkeypatch.setattr(Config, "ARTIFACT_STRICT_JSON", flag, raising=False)
        text, written = ra._forecast_artifact_json(finite, "forecast.json", record_quality=True)
        assert text == legacy and written is finite
    monkeypatch.setattr(Config, "ARTIFACT_STRICT_JSON", True, raising=False)
    prior = {"quality": {"nonfinite_nulled": ["$.old"]}, "x": _NAN}
    text, written = ra._forecast_artifact_json(prior, "forecast.json", record_quality=True)
    assert _strict_load(text)["quality"]["nonfinite_nulled"] == ["$.old", "$.x"]
    assert math.isnan(prior["x"]) and prior["quality"]["nonfinite_nulled"] == ["$.old"]


def test_forecast_artifact_json_survives_a_nonfinite_dict_key(monkeypatch):
    monkeypatch.setattr(Config, "ARTIFACT_STRICT_JSON", True, raising=False)
    key_only = {_NAN: 1, "a": 1}
    text, written = ra._forecast_artifact_json(key_only, "forecast.json", record_quality=True)
    assert text == json.dumps(key_only, ensure_ascii=False, indent=2)  # the legacy text
    assert _strict_load(text) == written == {"NaN": 1, "a": 1}
    mixed = {"a": {_INF: _NAN}, "quality": {}}
    text, written = ra._forecast_artifact_json(mixed, "forecast.json", record_quality=True)
    assert _strict_load(text) == written == {
        "a": {"Infinity": None}, "quality": {"nonfinite_nulled": ["$.a.Infinity"]}}


# ------------------------------------------------------------------ error classification
def _status_error(cls, status, message):
    response = httpx.Response(status, request=httpx.Request("POST", "http://127.0.0.1:1/v1"))
    return cls(message, response=response, body=None)


class _StatusExc(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.status_code = status


def test_classify_llm_error_status_first(monkeypatch):
    monkeypatch.setattr(Config, "LLM_ERROR_CLASSIFY_STATUS_FIRST", True, raising=False)
    rate = _status_error(openai.RateLimitError, 429, "Error code: 429 - invalid api key 401")
    auth = _status_error(openai.AuthenticationError, 401, "Error code: 401 - quota usage limit")
    assert lc._classify_llm_error(rate) == "quota"
    assert lc._classify_llm_error(auth) == "auth"
    assert lc._classify_llm_error(_StatusExc("denied; usage limit", 403)) == "auth"
    assert lc._classify_llm_error(_StatusExc("rejected", 401)) == "auth"
    assert lc._classify_llm_error(_StatusExc("busy", 429)) == "quota"
    assert lc._classify_llm_error(_StatusExc("unprocessable", 422)) == "content_filter"
    assert lc._classify_llm_error(lc.LLMContentFiltered("filtered")) == "content_filter"
    # wording: quota markers (incl. the new ones) before auth markers
    assert lc._classify_llm_error(RuntimeError("unauthorized: usage limit exceeded (2056)")) == "quota"
    assert lc._classify_llm_error(RuntimeError(_USAGE_CAP_401)) == "quota"
    assert lc._classify_llm_error(RuntimeError("code 1113: insufficient balance")) == "quota"
    assert lc._classify_llm_error(RuntimeError("status_code=2056")) == "quota"
    assert lc._classify_llm_error(RuntimeError("AuthenticationError: invalid authentication "
                                               "credentials")) == "auth"
    assert lc._classify_llm_error(_StatusExc("unknown provider for model X", 400)) \
        == "invalid_request"
    assert lc._classify_llm_error(RuntimeError("Connection reset by peer")) is None
    # the usage-cap codes only match as whole numbers
    assert lc._classify_llm_error(RuntimeError("request id req_20561 failed")) is None


def test_classify_llm_error_flag_off_keeps_legacy_order(monkeypatch):
    monkeypatch.setattr(Config, "LLM_ERROR_CLASSIFY_STATUS_FIRST", False, raising=False)
    assert lc._classify_llm_error(RuntimeError(_USAGE_CAP_401)) == "auth"
    # the legacy auth wording never matched a bare 'unauthorized', so this reads quota either way
    assert lc._classify_llm_error(RuntimeError("unauthorized: usage limit exceeded (2056)")) == "quota"
    assert lc._is_deterministic_auth_error(RuntimeError(_USAGE_CAP_401)) is True
    assert lc._classify_llm_error(RuntimeError("usage limit exceeded (2056)")) == "quota"
    # no status or new-marker reading: legacy _is_quota / auth wording only
    assert lc._classify_llm_error(_StatusExc("busy", 429)) is None
    assert lc._classify_llm_error(RuntimeError("code 1113: insufficient balance")) is None
    monkeypatch.setattr(Config, "LLM_ERROR_CLASSIFY_STATUS_FIRST", True, raising=False)
    assert lc._is_deterministic_auth_error(RuntimeError(_USAGE_CAP_401)) is False
    assert lc._is_deterministic_auth_error(RuntimeError("Error code: 401 - invalid key")) is True


def test_status_like_usage_cap_codes_stay_out_of_failure_messages(monkeypatch):
    monkeypatch.setattr(Config, "LLM_ERROR_CLASSIFY_STATUS_FIRST", True, raising=False)
    for max_tokens in (2056, 11130):
        exc = lc._completion_failure("minimax", "length", "length", None, max_tokens)
        assert str(max_tokens) not in str(exc) and exc.sent_max_tokens == max_tokens
        assert lc._classify_llm_error(exc) is None


@pytest.mark.parametrize("flag, attempts, consec429", [(True, lc.MAX_RETRIES, 3.0), (False, 1, 0.0)])
def test_chat_retries_a_usage_cap_that_reads_like_auth(monkeypatch, minimax_client,
                                                       flag, attempts, consec429):
    monkeypatch.setattr(Config, "LLM_ERROR_CLASSIFY_STATUS_FIRST", flag, raising=False)
    client, _transport = minimax_client
    calls = []

    def failing(self, *a, **kw):
        calls.append(1)
        raise RuntimeError(_USAGE_CAP_401)

    monkeypatch.setattr(lc.LLMClient, "_chat_openai", failing)
    with pytest.raises(RuntimeError, match="2056"):
        client.chat([{"role": "user", "content": f"infra4-cap-{flag}"}])
    assert len(calls) == attempts
    assert lc._CB_STATE.get("minimax", {}).get("consec429", 0.0) == consec429


def test_classify_provider_outage_quota_before_auth(monkeypatch):
    monkeypatch.setattr(Config, "LLM_ERROR_CLASSIFY_STATUS_FIRST", True, raising=False)
    assert po._classify_provider_outage(RuntimeError(_USAGE_CAP_401)) == "quota"
    assert po._classify_provider_outage("unauthorized: usage limit exceeded (2056)") == "quota"
    assert po._classify_provider_outage(
        _status_error(openai.AuthenticationError, 401, "Error code: 401 - quota usage limit")) \
        == "auth"
    assert po._classify_provider_outage(_StatusExc("busy", 429)) == "quota"
    assert po._classify_provider_outage(RuntimeError(
        "LLM 调用失败：主提供方 minimax 处于 422/429 熔断冷却，且回退提供方不可用")) == "circuit_breaker"
    assert po._classify_provider_outage(RuntimeError("AuthenticationError: invalid "
                                                     "authentication credentials")) == "auth"
    assert po._classify_provider_outage(_StatusExc("unprocessable new_sensitive", 422)) is None
    assert po._classify_provider_outage(RuntimeError("APIConnectionError: refused")) == "connection"
    monkeypatch.setattr(Config, "LLM_ERROR_CLASSIFY_STATUS_FIRST", False, raising=False)
    assert po._classify_provider_outage(RuntimeError(_USAGE_CAP_401)) == "auth"


# A Claude CLI credential failure: a 401 envelope whose duration and cost hold the digits 429.
_CLI_AUTH_ENVELOPE = ('Claude CLI failed (rc=1): {"type":"result","subtype":"success",'
                      '"is_error":true,"api_error_status":401,"duration_ms":1429,'
                      '"total_cost_usd":0.04291,"result":"Failed to authenticate. API Error: 401"}')


def test_status_first_reads_status_codes_as_whole_numbers(monkeypatch):
    monkeypatch.setattr(Config, "LLM_ERROR_CLASSIFY_STATUS_FIRST", True, raising=False)
    cli = RuntimeError(_CLI_AUTH_ENVELOPE)
    assert lc._classify_llm_error(cli) == "auth"
    assert lc._is_deterministic_auth_error(cli) is True
    assert po._classify_provider_outage(cli) == "auth"
    assert lc._classify_llm_error(RuntimeError(
        "Failed to authenticate (duration_ms 1429, cost 0.0429)")) == "auth"
    assert lc._classify_llm_error(RuntimeError(
        'Claude CLI failed (rc=1): {"api_error_status":429,"result":"busy"}')) == "quota"
    assert lc._classify_llm_error(RuntimeError("HTTP 429 Too Many Requests")) == "quota"
    assert lc._classify_llm_error(RuntimeError("错误码429：请求过多")) == "quota"
    # a 400 is an invalid request even when its text holds a usage-cap number
    for bad in (_StatusExc("Error code: 400 - prompt is 2056 tokens over the limit", 400),
                _status_error(openai.BadRequestError, 400, "prompt is 1113 tokens too long")):
        assert lc._classify_llm_error(bad) == "invalid_request"
        assert po._classify_provider_outage(bad) is None
    # flag off: the legacy wording order and the bare '429' substring
    monkeypatch.setattr(Config, "LLM_ERROR_CLASSIFY_STATUS_FIRST", False, raising=False)
    assert lc._classify_llm_error(cli) == "auth"
    assert lc._classify_llm_error(RuntimeError("duration_ms 1429")) == "quota"
    assert lc._classify_llm_error(
        _StatusExc("Error code: 400 - prompt is 2056 tokens over the limit", 400)) == "invalid_request"


def test_quota_codes_need_an_error_code_context(monkeypatch):
    """Review round 2: telemetry numbers and identifier segments never read as quota codes;
    the providers' real code shapes still do."""
    monkeypatch.setattr(Config, "LLM_ERROR_CLASSIFY_STATUS_FIRST", True, raising=False)
    null_status = RuntimeError('Claude CLI failed (rc=1): {"is_error":true,"api_error_status":null,'
                               '"duration_ms":2056,"num_turns":1,"total_cost_usd":0.1113,'
                               '"result":"Failed to authenticate. API Error: 401"}')
    assert lc._classify_llm_error(null_status) == "auth"
    assert lc._classify_llm_error(RuntimeError(
        "Authentication error: invalid key for project abcd-2056-ef01")) != "quota"
    assert lc._classify_llm_error(RuntimeError("timeout after 2056 ms")) is None
    for quota in ("HTTP429 Too Many Requests", "HTTP 429", "http/429",
                  '{"base_resp":{"status_code":2056,"status_msg":"token plan cap reached"}}',
                  '{"error":{"code":"1113","message":"余额不足或无可用资源包,请充值。"}}',
                  "Error code: 429 - please slow down", "状态码 2056"):
        assert lc._classify_llm_error(RuntimeError(quota)) == "quota", quota


def test_usage_cap_codes_reach_failure_messages_with_the_flag_off(monkeypatch):
    monkeypatch.setattr(Config, "LLM_ERROR_CLASSIFY_STATUS_FIRST", False, raising=False)
    assert "max_tokens=2056," in str(lc._completion_failure("minimax", "length", "length", None, 2056))
    assert "4290" not in str(lc._completion_failure("minimax", "length", "length", None, 4290))


@pytest.mark.parametrize("flag, consec429", [(True, float(lc.MAX_RETRIES)), (False, 0.0)])
def test_chat_with_tools_breaker_reads_the_same_quota_verdict(monkeypatch, minimax_client,
                                                             flag, consec429):
    monkeypatch.setattr(Config, "LLM_ERROR_CLASSIFY_STATUS_FIRST", flag, raising=False)
    client, transport = minimax_client
    calls = []

    def rate_limited(**kwargs):
        calls.append(kwargs)
        raise _status_error(openai.RateLimitError, 429, "Too many requests")

    transport.chat = SimpleNamespace(completions=SimpleNamespace(create=rate_limited))
    with pytest.raises(openai.RateLimitError):
        client.chat_with_tools([{"role": "user", "content": f"infra4-tools-{flag}"}], [])
    assert len(calls) == lc.MAX_RETRIES
    assert lc._CB_STATE.get("minimax", {}).get("consec429", 0.0) == consec429


# ------------------------------------------------------------------ prediction markets
class _FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=None, response=self)

    def json(self):
        return self._payload


@pytest.fixture
def markets_on(monkeypatch):
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)
    monkeypatch.setattr(pm, "_backoff_sleep", lambda attempt: None)


@pytest.mark.parametrize("payload", [{"pagination": {}}, {"events": "oops"}, [1, 2], None])
def test_search_events_records_invalid_200_schema(monkeypatch, markets_on, payload):
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: _FakeResponse(payload))
    client = pm.PolymarketClient()
    assert client.search_events("tariff") == []
    assert client.transport_errors == {"InvalidSchema:200": 1}
    assert client.last_error == {"error_class": "InvalidSchema", "http_status": 200,
                                 "url": pm.POLYMARKET_BASE_URL + "/public-search"}


def test_search_events_valid_or_failed_bodies_are_not_double_counted(monkeypatch, markets_on):
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: _FakeResponse({"events": []}))
    client = pm.PolymarketClient()
    assert client.search_events("tariff") == []
    assert client.transport_errors == {} and client.last_error is None
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: _FakeResponse(status_code=404))
    assert client.search_events("tariff") == []
    assert client.transport_errors == {"HTTPStatusError:404": 1}


# ------------------------------------------------------------------ backfill script
def _anchored_forecast(implied):
    return {"binary_forecasts": [{
        "id": "F1", "statement": "Real outcome", "probability": 0.7,
        "market_anchor": {"market_id": "m1", "question": "Will it happen?",
                          "implied_yes_prob": implied}}]}


def test_backfill_never_writes_nonfinite_artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "ARTIFACT_STRICT_JSON", True, raising=False)
    forecast = _anchored_forecast(_INF)
    comparison = bf.synchronize_market_comparison(tmp_path, forecast)
    standalone = _strict_load((tmp_path / "market_comparison.json").read_text(encoding="utf-8"))
    row = standalone["comparisons"][0]
    assert row["market_implied_yes_prob"] is None and row["divergence"] is None
    assert row["model_probability"] == 0.7
    assert numeric.find_nonfinite(comparison)  # memory keeps the value until forecast.json
    written = bf._write_forecast_artifact(tmp_path / "forecast.json", forecast, record_quality=True)
    on_disk = _strict_load((tmp_path / "forecast.json").read_text(encoding="utf-8"))
    assert on_disk == written and on_disk["market_comparison"] == standalone
    assert on_disk["quality"]["nonfinite_nulled"] == numeric.find_nonfinite(forecast)
    assert forecast["binary_forecasts"][0]["market_anchor"]["implied_yes_prob"] == _INF


@pytest.mark.parametrize("flag", [True, False])
def test_backfill_finite_writes_are_byte_identical(monkeypatch, tmp_path, flag):
    monkeypatch.setattr(Config, "ARTIFACT_STRICT_JSON", flag, raising=False)
    forecast = _anchored_forecast(0.5)
    comparison = bf.synchronize_market_comparison(tmp_path, forecast)
    assert bf._write_forecast_artifact(tmp_path / "forecast.json", forecast,
                                       record_quality=True) is forecast
    for name, obj in (("market_comparison.json", comparison), ("forecast.json", forecast)):
        assert (tmp_path / name).read_text(encoding="utf-8") \
            == json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def test_backfill_flag_off_writes_nonfinite_as_before(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "ARTIFACT_STRICT_JSON", False, raising=False)
    forecast = _anchored_forecast(_INF)
    bf._write_forecast_artifact(tmp_path / "forecast.json", forecast, record_quality=True)
    text = (tmp_path / "forecast.json").read_text(encoding="utf-8")
    assert text == json.dumps(forecast, ensure_ascii=False, indent=2, default=str)
    assert "Infinity" in text and "nonfinite_nulled" not in text


# ------------------------------------------------------------------ knobs
def test_knobs_default_on_and_documented():
    knobs = extract_knobs()
    with open(os.path.join(_REPO_ROOT, ".env.example"), encoding="utf-8") as handle:
        text = handle.read()
    for name in _KNOBS:
        assert getattr(Config, name) is True, name
        assert knobs[name]["kind"] == "bool" and knobs[name]["default"] == "true", name
        assert knobs[name]["attr"] == name, name
        assert f"# {name}=true" in text, name
